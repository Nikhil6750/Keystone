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
information, timestamps, and version.

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
`agent_type` has no registered executor. **No real executors are registered until
Phase 3**, so this is the expected response for any execution attempt today.

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

| HTTP status | `code`                          |
| ----------- | -------------------------------- |
| 404         | `WORKFLOW_NOT_FOUND`             |
| 409         | `INVALID_WORKFLOW_STATE`         |
| 422         | `INVALID_REQUEST`                |
| 503         | `AGENT_EXECUTOR_NOT_REGISTERED`  |
| 500         | `INTERNAL_ERROR` (unexpected)    |

`STEP_EXECUTION_FAILED` is not currently returned via this envelope: an *expected* step
execution failure is normal workflow execution and comes back as a `200` response with
the failed workflow body (see `POST .../execute` above). The code is reserved for that
failure mode should it ever need to be surfaced as an API-level error.

Error responses never include stack traces, database URLs, or internal configuration.

## Planned, not yet implemented

Retry, compensation, and audit endpoints will be added here as they are implemented.
They do not exist yet. Real agent executors are not registered until Phase 3 — until
then, `POST /api/v1/workflows/{workflow_id}/execute` always returns `503` for any
workflow with at least one step.
