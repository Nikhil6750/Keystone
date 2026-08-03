# Keystone API Contract

This document tracks the REST API surface as it is implemented. Only endpoints that
actually exist in `backend/app/` are listed here.

## Base URL

Local development: `http://localhost:8000`

## Endpoints

### `GET /`

Root endpoint confirming the service is running.

**Response `200 OK`**

```json
{
  "service": "keystone-backend",
  "version": "0.1.0"
}
```

### `GET /api/v1/health`

Health check endpoint.

**Response `200 OK`**

```json
{
  "status": "healthy",
  "service": "keystone-backend",
  "version": "0.1.0"
}
```

### `POST /api/v1/workflows`

Validates and persists a new workflow with its ordered steps in one transaction. Does
**not** execute it.

**Request body** (`WorkflowCreate`; unknown fields rejected)

```json
{
  "name": "demo",
  "description": null,
  "input_payload": {},
  "steps": [
    {
      "name": "step-1",
      "position": 0,
      "agent_type": "mock",
      "input_payload": {},
      "max_attempts": 3,
      "compensation_handler": null
    }
  ]
}
```

Clients cannot supply `id`, `status`, timestamps, `attempt_count`, or `version` — these
are always server-assigned.

**Response `201 Created`**: the persisted workflow (`WorkflowRead`), steps ordered by
position.

**Response `422 Unprocessable Entity`**: validation failure (empty name, invalid step,
duplicate step positions, unknown field) — see "Error responses" below.

### `GET /api/v1/workflows/{workflow_id}`

Retrieves one workflow with its ordered steps and each step's attempt history.

**Response `200 OK`**: `WorkflowRead` — includes status, input/output payloads, error
information, timestamps, version, and `compensation_summary` (`null` until
compensation runs). Each step also carries its own `compensation_attempts`.

**Response `404 Not Found`**: `WORKFLOW_NOT_FOUND`.

### `GET /api/v1/workflows`

Lists workflows newest-first.

**Query parameters**

- `limit` — integer, default `50`, minimum `1`, maximum `100`. Out-of-range values
  return `422 INVALID_REQUEST`.

**Response `200 OK`**

```json
{
  "items": [],
  "count": 0
}
```

`count` is always `len(items)` for the returned page — not a total database count.

### `POST /api/v1/workflows/{workflow_id}/execute`

Synchronously executes a `PENDING` workflow's steps in ascending position order, then
returns the updated workflow. There is no background job or polling — the HTTP request
blocks until execution finishes (or fails).

Only a `PENDING` workflow may begin execution.

**Response `200 OK`**: the updated `WorkflowRead`, whether the workflow **succeeded** or
a step raised an *expected* execution error (persisted as `FAILED` with `error_message`
set — this is normal workflow execution, not an API error).

**Response `404 Not Found`**: `WORKFLOW_NOT_FOUND` — the workflow does not exist.

**Response `409 Conflict`**: `INVALID_WORKFLOW_STATE` — the workflow is not `PENDING`
(e.g., already running, already succeeded, already failed).

**Response `503 Service Unavailable`**: `AGENT_EXECUTOR_NOT_REGISTERED` — a step's
`agent_type` has no registered executor (e.g., the provider is disabled or its CLI
is not installed), or `CIRCUIT_BREAKER_OPEN` — a step's agent type has an open
circuit breaker (see below); the adapter was never invoked for that attempt.

If a step's failure is marked retryable and it has attempts remaining, execution
retries it (bounded exponential backoff) before finally failing; retry history is
recorded as additional `StepAttempt` rows on the same step, visible via `GET
/api/v1/workflows/{workflow_id}`.

### `GET /api/v1/agents`

Reports configuration/availability/registration status for all four canonical agent
types (`claude_code`, `codex`, `gemini`, `demo`), in that stable order.

**Response `200 OK`**

```json
{
  "items": [
    {
      "agent_type": "claude_code",
      "enabled": false,
      "available": true,
      "registered": false,
      "execution_mode": "local_cli",
      "reason": "Disabled by configuration"
    }
  ],
  "count": 4
}
```

- `enabled` — whether the agent type is turned on in settings.
- `available` — whether its configured executable can currently be resolved
  (`shutil.which`); always `false` for a disabled agent. Does **not** mean
  authentication was verified — only a real execution proves that.
- `registered` — whether the adapter is registered in the current application's
  executor registry.
- `execution_mode` — `"local_cli"` for Claude Code/Codex/Gemini, `"demo"` for demo.
- `reason` — a short, safe explanation. Never includes absolute executable paths,
  CLI arguments, or any secret.

No local agent CLI (`claude`, `codex`, `gemini`) is installed, authenticated, or
started by Keystone itself — each must already be installed and authenticated
(subscription-based login) separately by the operator.

### `GET /api/v1/resilience/circuit-breakers`

Returns a snapshot of every per-agent-type circuit breaker created so far (a
breaker is created lazily, the first time that agent type is used).

**Response `200 OK`**

```json
{
  "items": [
    {
      "agent_type": "claude_code",
      "state": "closed",
      "failure_count": 0,
      "failure_threshold": 3,
      "recovery_timeout_seconds": 30.0,
      "retry_after_seconds": 0.0,
      "half_open_probe_in_flight": false
    }
  ],
  "count": 1
}
```

- `state` — one of `closed`, `open`, `half_open`.
  - `closed`: calls are allowed; failures accumulate toward `failure_threshold`.
  - `open`: calls are rejected immediately (no subprocess launched) until
    `recovery_timeout_seconds` has elapsed since opening.
  - `half_open`: exactly one probe call is allowed; success closes the circuit,
    failure reopens it.
- `retry_after_seconds` — never negative; `0` unless `state` is `open`.
- Breaker state is in-memory only and does not survive an application restart
  (restarting the process is the prototype's manual reset — there is no reset
  endpoint in this phase).

### `POST /api/v1/workflows/{workflow_id}/compensate`

Compensates a workflow's already-successful steps in **descending position order**
(reverse of execution order), running each step's configured `compensation_handler`.
Synchronous, like `.../execute` — the request blocks until compensation finishes.

Only a `FAILED` or `SUCCEEDED` workflow may be compensated, and only once.

**Response `200 OK`**: the updated `WorkflowRead` — `status: "compensated"` on full
success, or `status: "failed"` if a step's compensation handler raised an *expected*,
handled failure (this is normal compensation execution, not an API error — mirrors how
an expected step-execution failure returns `200` from `.../execute`). `steps[].
compensation_attempts` and the top-level `compensation_summary` reflect what was
attempted. A step with no `compensation_handler` configured is skipped and listed under
`compensation_summary.not_configured_steps`, never attempted.

**Response `404 Not Found`**: `WORKFLOW_NOT_FOUND`.

**Response `409 Conflict`**: `INVALID_COMPENSATION_STATE` — the workflow is not
`FAILED`/`SUCCEEDED` (e.g. still `PENDING`/`RUNNING`/`COMPENSATING`); or
`COMPENSATION_ALREADY_COMPLETED` — the workflow is already `COMPENSATED`.

**Response `503 Service Unavailable`**: `COMPENSATION_HANDLER_NOT_REGISTERED` — an
eligible step's `compensation_handler` name has no registered handler; the workflow
stays `FAILED` and no further steps are compensated.

### `GET /api/v1/workflows/{workflow_id}/audit-events`

Lists a workflow's hash-linked audit events in sequence order.

**Query parameters**

- `limit` — integer, default `100`, minimum `1`, maximum `500`. Out-of-range values
  return `422`.

**Response `200 OK`**

```json
{
  "items": [
    {
      "id": "...",
      "workflow_id": "...",
      "step_id": null,
      "execution_attempt_id": null,
      "compensation_attempt_id": null,
      "sequence_number": 1,
      "event_type": "workflow_created",
      "actor_type": "user",
      "actor_id": "api",
      "payload": {},
      "previous_hash": "000...000",
      "event_hash": "3f2a...",
      "created_at": "2026-01-01T00:00:00+00:00"
    }
  ],
  "count": 1
}
```

**Response `404 Not Found`**: `WORKFLOW_NOT_FOUND`.

### `GET /api/v1/workflows/{workflow_id}/audit-chain/verify`

Verifies a workflow's full audit chain: contiguous sequence numbers from `1`, each
event's `previous_hash` linking to the prior event's `event_hash` (the genesis hash —
64 `"0"` characters — for the first event), and each event's own `event_hash` matching
its recomputed hash.

**Always returns `200 OK`** — an invalid chain (`valid: false`) is a verification
*result*, not a transport failure.

```json
{
  "workflow_id": "...",
  "valid": true,
  "event_count": 12,
  "first_invalid_sequence": null,
  "reason": null
}
```

If `valid` is `false`, `first_invalid_sequence` and `reason` identify the earliest
broken event; verification stops there rather than reporting every subsequent
discrepancy.

**Response `404 Not Found`**: `WORKFLOW_NOT_FOUND`.

### `GET /api/v1/workflows/{workflow_id}/provenance`

Returns a workflow's full ordered audit trail together with its chain validity, in one
call — the same event shape as `.../audit-events`.

**Response `200 OK`**

```json
{
  "workflow_id": "...",
  "chain_valid": true,
  "events": []
}
```

**Response `404 Not Found`**: `WORKFLOW_NOT_FOUND`.

## Error responses

All handled errors share one envelope:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Readable explanation",
    "details": null
  }
}
```

| HTTP status | `code`                              |
| ----------- | ----------------------------------- |
| 404         | `WORKFLOW_NOT_FOUND`                |
| 409         | `INVALID_WORKFLOW_STATE`            |
| 409         | `INVALID_COMPENSATION_STATE`        |
| 409         | `COMPENSATION_ALREADY_COMPLETED`    |
| 422         | `INVALID_REQUEST`                   |
| 503         | `AGENT_EXECUTOR_NOT_REGISTERED`     |
| 503         | `CIRCUIT_BREAKER_OPEN`              |
| 503         | `COMPENSATION_HANDLER_NOT_REGISTERED` |
| 500         | `COMPENSATION_EXECUTION_FAILED` (unexpected leak only — normally returned as `200`) |
| 500         | `INTERNAL_ERROR` (unexpected)        |

`STEP_EXECUTION_FAILED` is not currently returned via this envelope: an *expected* step
execution failure is normal workflow execution and comes back as a `200` response with
the failed workflow body (see `POST .../execute` above). The code is reserved for that
failure mode should it ever need to be surfaced as an API-level error. `AUDIT_CHAIN_INVALID`
and `AUDIT_EVENT_CONFLICT` are reserved the same way: `.../audit-chain/verify` always
returns `200` (an invalid chain is a verification result, not a transport error), and an
audit-append sequence-number race is retried internally and never surfaces as an API-level
conflict in practice.

Error responses never include stack traces, database URLs, or internal configuration.

## Planned, not yet implemented

No public circuit-breaker reset endpoint exists in this phase. Provider-backed
compensation handlers (reversing a real external side effect, rather than the demo
handler) are not yet implemented.
