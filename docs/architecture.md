# Keystone AI — Architecture

This document describes the intended module layout for the Keystone backend. It reflects
the target design, not the current implementation state — see the "Implementation status"
note under each module. For the Next.js frontend's architecture and how it integrates
with the API described here, see [`phase5-integration.md`](./phase5-integration.md).

## Overview

Keystone AI orchestrates workflows across multiple LLM agents, aiming to keep those
workflows fault-tolerant: individual agent failures should be retried, circuit-broken, or
compensated for, rather than taking down the whole workflow. Every state transition is
recorded in a tamper-evident, hash-linked audit log.

## Backend modules (`backend/app/`)

### `core/`
Application-wide configuration and logging setup.
**Implementation status: implemented.** `core/config.py` defines settings loaded from
environment variables via Pydantic Settings; `core/logging.py` configures structured
logging.

### `api/`
FastAPI routers exposing the REST API described in [`api-contract.md`](./api-contract.md).
**Implementation status: implemented.** `api/routes/health.py` (root/health),
`api/routes/workflows.py` (create/get/list/execute workflows, plus
`POST /{id}/compensate`), `api/routes/agents.py` (`GET /agents`),
`api/routes/resilience.py` (`GET /resilience/circuit-breakers`), and
`api/routes/audit.py` (`GET /{id}/audit-events`, `GET /{id}/audit-chain/verify`,
`GET /{id}/provenance`) exist. `api/deps.py` provides the request-scoped
`WorkflowEngine`/`ExecutorRegistry`/`CircuitBreakerRegistry`/`RetryPolicy`/
`CompensationRegistry`/`CompensationService` dependencies, each reading its
application-scoped instance from `request.app.state` (the registries) or
constructing a per-request service from them; `api/errors.py` maps domain
exceptions — including `CircuitBreakerOpenError` → `503 CIRCUIT_BREAKER_OPEN`,
`CompensationHandlerNotRegisteredError` → `503`, `InvalidCompensationStateError`/
`CompensationAlreadyCompletedError` → `409` — and FastAPI validation errors to the
`{"error": {...}}` envelope (see api-contract.md).

### `schemas/`
Pydantic models defining request and response shapes for the API layer.
**Implementation status: implemented.** `schemas/health.py`, `schemas/workflow.py`
(`WorkflowCreate`, `WorkflowStepCreate`, `WorkflowRead`, `WorkflowStepRead`,
`StepAttemptRead`, `CompensationAttemptRead`, `WorkflowListResponse`) —
`WorkflowRead` carries `compensation_summary` and each `WorkflowStepRead` carries
its `compensation_attempts` — `schemas/errors.py` (`APIErrorCode`, `APIError`,
`APIErrorEnvelope`), `schemas/agents.py` (`AgentAvailabilityRead`,
`AgentAvailabilityListResponse`), `schemas/resilience.py` (`CircuitBreakerRead`,
`CircuitBreakerListResponse`), and `schemas/audit.py` (`AuditEventRead`,
`AuditEventListResponse`, `ChainVerificationRead`, `ProvenanceRead`) exist and
back the API routes.

### `database/`
SQLAlchemy engine/session setup and persistence of workflow state to SQLite.
**Implementation status: implemented.** `database/base.py` defines the typed declarative
base; `database/session.py` centralizes engine and session creation (SQLite foreign-key
enforcement enabled per connection) and exposes a `get_db()` FastAPI dependency for later
use; `database/init_db.py` exposes `initialize_database()`, called from the FastAPI
lifespan on startup to create tables if they don't already exist. No connection is opened
and no tables are created at import time.

### `models/`
SQLAlchemy ORM models representing workflows, steps, and agent invocations.
**Implementation status: implemented.** `models/enums.py` defines `WorkflowStatus`,
`StepStatus`, `AttemptStatus`, and `CompensationAttemptStatus`. `models/workflow.py`
defines `Workflow` (the top-level orchestration unit, versioned, with an ordered
`steps` relationship, a nullable `compensation_summary` JSON column populated only
once compensation runs, and an ordered `audit_events` relationship).
`models/workflow_step.py` defines `WorkflowStep` (one ordered, retryable unit of work
per workflow, unique by `(workflow_id, position)`, with a nullable
`compensation_handler` name and an ordered `compensation_attempts` relationship).
`models/step_attempt.py` defines `StepAttempt` (retained execution-attempt history per
step, unique by `(step_id, attempt_number)`). `models/compensation_attempt.py` defines
`CompensationAttempt` (one compensation-handler invocation per step, unique by
`(step_id, attempt_number)` — a separate sequence from `StepAttempt`, since a
compensation attempt reverses an already-successful step rather than executing it).
`models/audit_event.py` defines `AuditEvent` (one hash-linked entry in a workflow's
audit chain — see `audit/` below). Deleting a workflow cascades to its steps,
attempts, compensation attempts, and audit events at both the ORM and database level.

### `engine/`
The workflow orchestration engine: sequencing steps, tracking workflow state, and
invoking agents through adapters.
**Implementation status: partially implemented.** `engine/state_machine.py` implements
and validates all workflow and step state transitions (`transition_workflow`,
`transition_step`, raising `InvalidStateTransition` on disallowed transitions) and owns
timestamp/version bookkeeping.

`engine/workflow_engine.py`'s `WorkflowEngine` executes a `PENDING` workflow's steps
synchronously and sequentially in position order, given a database session and an
`ExecutorRegistry`:

- Resolves each step's executor by `agent_type` (`engine/registry.py`,
  `ExecutorRegistry.get`), raising `ExecutorNotRegisteredError` if none is registered.
- Calls the executor through the `AgentExecutor` protocol (`engine/executor.py`), passing
  a `StepExecutionRequest` and validating the JSON-compatibility of its output.
- Threads an immutable `ExecutionContext` (`engine/context.py`) through the steps,
  accumulating each successful step's output keyed by stable step ID (never step name,
  since names may repeat) without mutating the workflow's persisted input payload.
- Persists progress through the existing state machine and `workflow_service` at
  deliberate boundaries — entering `RUNNING`, each attempt's creation, each attempt's
  completion, each step's terminal status, and the workflow's final status/result — so a
  failure partway through never erases already-committed history.
- On success, aggregates step outputs in position order into
  `{"steps": [{"step_id", "name", "position", "output"}, ...]}` and stores it as the
  workflow's `output_payload`.
- Before every external call (including retries), checks a per-agent-type circuit
  breaker (`resilience/circuit_breaker.py`); an already-open circuit rejects the call
  without ever invoking the adapter, persisting one blocked `StepAttempt` with
  `error_type="CIRCUIT_BREAKER_OPEN"` and re-raising `CircuitBreakerOpenError` (mapped
  to `503` by the API layer).
- On a `StepExecutionError` marked `retryable=True` (see `engine/executor.py`), retries
  while the step has attempts remaining (`WorkflowStep.max_attempts`, which counts the
  first attempt) and the circuit still permits a call: completes the failed attempt,
  transitions the step `RUNNING → RETRYING`, sleeps for a bounded exponential-backoff
  delay (`resilience/retry.RetryPolicy`, via an injected `Sleeper` so tests never
  actually wait), transitions back to `RUNNING`, and creates the next attempt. If the
  failure itself opens the circuit, no further retry is attempted for that step
  regardless of attempts remaining.
- On any other step failure — non-retryable, retries exhausted, or a missing executor
  (`ExecutorNotRegisteredError`) — persists the step/attempt/workflow as `FAILED` with a
  safe error message, and stops; later steps are left `PENDING`. A missing executor or
  an open circuit re-raises (mapped to `503`); an expected step failure (retryable or
  not) that ultimately fails returns the persisted `FAILED` workflow normally (`200` at
  the API layer — a step failure is normal workflow execution, not an API error).
  Unexpected exceptions are also persisted as a sanitized `FAILED` state, logged with
  full detail server-side, and re-raised (mapped to `500`).
- `engine/exceptions.py` defines `WorkflowNotFoundError` and `InvalidWorkflowStateError`,
  raised before execution starts (missing workflow / not `PENDING`) and shared with the
  API's `GET /workflows/{id}` route.
- `circuit_breakers` and `retry_policy` are constructor-injected (defaulting to
  conservative built-in settings so the original two-argument Phase 2 constructor call
  keeps working); the real application builds them from settings once per process, in
  `main.py`'s lifespan, and injects them via `api/deps.py`.
- Every execution milestone (workflow/step start, each attempt's start/success/failure,
  retry scheduling, circuit rejection, workflow success/failure) is recorded as a
  hash-linked `AuditEvent` (see `audit/` below) immediately after the state transition
  that produced it commits — never before, and never for a transition that didn't
  actually commit.
- `compensation_registry` (optional) and `auto_compensate_on_failure` (default `False`)
  are also constructor-injected; when a registry is provided, the engine builds its own
  `CompensationService` and, after a workflow reaches `FAILED` via the
  `ExecutorNotRegisteredError`, `CircuitBreakerOpenError`, or `StepExecutionError` paths
  (never the generic-unexpected-exception path — an unknown internal bug should not
  trigger automatic reversal), calls it best-effort: any exception during automatic
  compensation is logged and swallowed rather than propagated, since
  `CompensationService` already durably persists its own failure before any exception
  would reach the engine.

#### Saga-style compensation (`engine/compensation*.py`)

**Implementation status: implemented.** A failed workflow can be compensated — either
manually via `POST /api/v1/workflows/{id}/compensate` or automatically (see above) — by
reversing its already-successful steps in **descending position order** (last
successful step undone first), exactly mirroring how a saga unwinds.

- `compensation_context.py` — `CompensationRequest`, an immutable, typed bundle a
  handler receives: workflow/step identity, the step's own input/output, every
  previously-produced step output, and the workflow's original failure message —
  never a raw exception or stack trace.
- `compensation_executor.py` — `CompensationExecutor`, a `Protocol` with a single
  `compensate(request) -> dict[str, Any]` method, mirroring `AgentExecutor`'s shape.
- `compensation_registry.py` — `CompensationRegistry`, a per-application, in-process
  name → handler map (never a module-level singleton), mirroring `ExecutorRegistry`.
- `compensation_exceptions.py` — `CompensationError` and its subclasses:
  `CompensationHandlerNotRegisteredError` (an *infrastructure* gap — raised, mapped to
  `503`, since the operator must register a handler before compensation can proceed);
  `CompensationExecutionError` (an *expected*, handled compensation failure — caught
  internally and the `FAILED` workflow is returned normally, `200`, exactly like a
  handled `StepExecutionError`); `CompensationAlreadyCompletedError` /
  `InvalidCompensationStateError` (state-precondition violations, `409`).
- `demo_compensation.py` — `DemoCompensationHandler` (`demo.undo`): no subprocess, no
  network, clearly labels its output `metadata.execution_mode="demo"` and
  `compensation=True`; registered only when `KEYSTONE_DEMO_ENABLED=true`. Lives in
  `engine/`, not `adapters/`, since a real provider-backed compensation handler (e.g.
  "revert this file edit," "cancel this ticket") is a Phase 5+ concern.
- `compensation.py` — `CompensationService.compensate_workflow(workflow_id)`:
  - **Workflow eligibility** (the workflow's own status): manual compensation may
    only begin from `FAILED`. An already-`COMPENSATED` workflow raises
    `CompensationAlreadyCompletedError` (`409`); every other status — `PENDING`,
    `RUNNING`, `SUCCEEDED`, `COMPENSATING`, or `CANCELLED` — raises
    `InvalidCompensationStateError` (`409`). A `SUCCEEDED` workflow can never be
    manually compensated: the state machine itself gives `WorkflowStatus.SUCCEEDED`
    zero allowed outgoing transitions (see `state_machine.py`'s
    `WORKFLOW_TRANSITIONS`), so there is no path from `SUCCEEDED` to `COMPENSATING`
    even before this check runs.
  - **Step eligibility** (independent of workflow status, evaluated only once the
    workflow itself is confirmed `FAILED`): a step is eligible only if it
    individually reached `SUCCEEDED` *and* has a non-blank `compensation_handler`
    configured — this is what "eligible successful step" means throughout this
    document; it is never a claim about the workflow's own status. Eligible steps
    are sorted by `position` **descending**; a `SUCCEEDED` step with no handler
    configured is recorded (in the summary) as `not_configured`, not attempted.
  - Transitions the workflow `FAILED → COMPENSATING`, then each eligible step
    `SUCCEEDED → COMPENSATING`, persisting one `CompensationAttempt` per step.
  - On a missing handler: persists the failed attempt and step, then **re-raises**
    `CompensationHandlerNotRegisteredError` (the workflow stays `FAILED`, `503`).
  - On a handled `CompensationExecutionError` (or any other handler exception —
    treated the same as a handled failure, never leaking a raw traceback): persists
    the failed attempt/step, stops compensating further steps, and **returns** the
    `FAILED` workflow normally (`200`) — already-succeeded compensations from earlier
    in this same run remain persisted, they are not rolled back.
  - On full success: transitions the workflow `COMPENSATING → COMPENSATED`, persists a
    `compensation_summary` (`{"compensated_steps": [...], "not_configured_steps":
    [...], "failed_compensation_step": ...}`), and returns the reloaded workflow.
  - Idempotent by construction: calling it again on an already-`COMPENSATED` workflow
    raises `CompensationAlreadyCompletedError` before any handler is invoked.
  - Every milestone — compensation started/succeeded/failed at both the workflow and
    step level, and each attempt's start/success/failure — is recorded as a hash-linked
    `AuditEvent`.

Compensation is **best-effort reversal**, not a distributed transaction or two-phase
commit: a handler that appears to succeed but doesn't fully reverse external side
effects (e.g. a partially-refunded charge) is indistinguishable from a fully successful
one at this layer. Provider-backed compensation handlers (calling a real external
system to undo a step) are out of scope for this prototype; only the demo handler and
the test-only fakes exist today.

### `adapters/`
Local CLI integration layers between the orchestration engine and individual coding
agents. **Implementation status: implemented**, for local-CLI-based execution.

Keystone never calls a paid HTTP API and never stores or reads credentials itself —
every adapter shells out to an **already-installed, already-authenticated** local CLI
(subscription-based login, managed entirely by that CLI). If the CLI is missing or not
authenticated, the adapter is simply unavailable; Keystone never attempts to install a
CLI or drive an interactive login.

- `types.py` — the four canonical agent types (`claude_code`, `codex`, `gemini`,
  `demo`); `CLIProfile` (trusted, settings-derived configuration: executable, argument
  list, input/output mode, timeout, output cap) and `create_cli_profile`, the single
  place that validates a profile (blank executable, non-positive timeout, invalid
  input/output mode, unsafe shell-string arguments, wrong prompt-placeholder count all
  rejected with `ValueError`).
- `exceptions.py` — `AgentAdapterError` and its subclasses (`AgentUnavailableError`,
  `AgentConfigurationError`, `AgentTimeoutError`, `AgentProcessError`,
  `AgentOutputError`), each a `StepExecutionError` subclass carrying a stable
  `error_code` and whether the engine should retry it.
- `process_runner.py` — the safe subprocess execution boundary (see below).
- `prompt_builder.py` — one deterministic, JSON-serializing prompt builder shared by
  every local CLI adapter (never `str()`/`repr()` of Python objects), rejecting
  oversized prompts as a non-retryable `AgentConfigurationError`.
- `local_cli.py` — `LocalCLIAdapter`, the shared `AgentExecutor` implementation:
  builds the prompt, passes it via stdin or a `{prompt}` argument placeholder per the
  profile's `input_mode`, runs the process, and parses `text`/`json`/`json_lines`
  output into the stable result envelope
  `{"agent_type", "content", "metadata": {"execution_mode": "local_cli", ...}}`.
- `claude_code.py`, `codex.py`, `gemini.py` — thin `LocalCLIAdapter` subclasses, one
  per provider, each carrying its own agent type via its `CLIProfile`.
- `demo.py` — `DemoAgentAdapter`, a deterministic, no-subprocess, no-network adapter
  for local demonstration and frontend integration. Disabled by default; registers only
  when explicitly enabled; always labels its result `metadata.execution_mode="demo"`
  and its content `[DEMO] ...`; never registered under a real provider's agent type.
- `factory.py` — `register_agents`, called once from the FastAPI lifespan: builds each
  real provider's `CLIProfile` from settings, registers it only if enabled *and* its
  executable resolves via `shutil.which`, and registers the demo adapter only if
  explicitly enabled. Never launches a real agent process and never fails application
  startup because one optional agent is disabled, misconfigured, or unavailable.

#### Process-runner security boundary (`adapters/process_runner.py`)

`SubprocessRunner` is the only place Keystone launches an external process. It:

- always calls `subprocess.run(..., shell=False)` with the command as a list — never a
  shell string, never `cmd.exe /c`, never a Bash `-c` string;
- resolves the executable via `shutil.which` first, raising `AgentUnavailableError` if
  it can't be found;
- runs in a fresh `tempfile.TemporaryDirectory`, never the Keystone repository, cleaned
  up automatically on every exit path;
- passes a **restricted** environment (a small allow-list — `PATH`, `SYSTEMROOT`,
  `TEMP`/`TMP`, `HOME`/`USERPROFILE` — plus only explicit, settings-derived overrides),
  never the full parent environment;
- enforces `timeout_seconds` (→ `AgentTimeoutError`) and `max_output_characters` (→
  `AgentOutputError`);
- maps a non-zero exit to `AgentProcessError`, with `stderr` bounded and sanitized
  before it ever reaches a persisted attempt or a log line.

Only trusted, settings-derived `executable`/`arguments` ever reach this layer — nothing
in a workflow payload can set an executable path, a CLI flag, a working directory, or
an environment override; `StepExecutionRequest` carries only step/workflow data.

### `resilience/`
Retry policies and circuit breakers applied around agent adapter calls, so transient
agent failures don't cascade into workflow failures. **Implementation status:
implemented**, both owned and invoked exclusively by `engine/workflow_engine.py`.

- `clock.py` / `sleeper.py` — injectable monotonic clock and sleep, so circuit-breaker
  and retry tests are deterministic and never actually wait.
- `retry.py` — `RetryPolicy`: bounded exponential backoff,
  `delay = min(max_delay, base_delay * 2^(failed_attempt_number - 1))` plus optional
  bounded jitter (injectable jitter provider); never negative, never exceeds
  `max_delay_seconds`.
- `circuit_breaker.py` — `CircuitBreaker`: an in-memory, thread-safe (single lock, never
  held across an external call), per-agent-type breaker with `CLOSED`/`OPEN`/
  `HALF_OPEN` states, and `CircuitBreakerRegistry`, which owns one breaker per
  normalized agent type. **In-memory only — state does not survive an application
  restart**; restarting the process is this prototype's accepted manual reset (no
  reset endpoint exists).

### `services/`
Application services that coordinate the engine, adapters, and persistence layer on
behalf of the API layer (e.g., "start a workflow," "compensate a failed step").
**Implementation status: implemented.** `services/workflow_service.py` implements
workflow/step/attempt persistence: `create_workflow` (workflow plus its ordered steps
in one transaction, rolled back entirely on failure), `get_workflow`, `list_workflows`,
`transition_workflow`, `transition_step`, `create_step_attempt`,
`complete_step_attempt`, `set_workflow_result` (persists a workflow's aggregated
`output_payload` and/or `error_message` without changing its status), and — added for
compensation — `set_compensation_summary` (touches *only* `compensation_summary`,
deliberately separate from `set_workflow_result` so compensating a workflow never
overwrites its original execution output or error message), `create_compensation_attempt`,
and `complete_compensation_attempt`. Each state-changing operation persists through the
state machine in `engine/state_machine.py` within a single transaction, rolling back and
re-raising on invalid transitions or database errors. `services/agent_availability.py`
reports each canonical agent type's enabled/available/registered status and a safe
reason string (never an absolute executable path or CLI arguments) for
`GET /api/v1/agents`. `WorkflowEngine` (`engine/workflow_engine.py`) and
`CompensationService` (`engine/compensation.py`) are the higher-level orchestration
services for execution and compensation respectively.

### `audit/`
A hash-linked, append-only log of workflow, step, attempt, and compensation events, so
that after-the-fact audits can detect tampering (each event's hash incorporates the
previous event's hash — see the "Tamper-evident audit chain" section below).
**Implementation status: implemented.**

## Tamper-evident audit chain (`audit/`)

Every workflow has its own append-only, SHA-256 hash-linked chain of `AuditEvent` rows,
sequenced from `1` per workflow. This is **tamper-evident, not tamper-proof**: it proves
whether the persisted chain is internally self-consistent, not that no one with direct
database access ever altered it (see the "Known limitations" note below).

- `types.py` — `AuditEventType` (workflow/step/attempt/compensation lifecycle events —
  e.g. `workflow_execution_started`, `step_succeeded`, `compensation_attempt_failed`)
  and `ActorType` (`user`/`system`/`agent`/`compensation_handler`), defined once and
  imported everywhere an event is appended.
- `canonical.py` — `canonical_json`: the single, deterministic serialization used for
  hashing (`sort_keys=True`, compact separators, UTF-8, only plain JSON scalar/list/dict
  types accepted — never Python `repr`, never a `set`/`datetime`/custom object, which
  would silently break determinism).
- `hashing.py` — `GENESIS_HASH` (64 `"0"` characters, the `previous_hash` of sequence
  `1`); `build_hash_envelope(...)`, the exact documented set of hashed fields
  (deliberately excluding the event's own `event_hash` and database `id` — a hash must
  never hash itself); `compute_event_hash`, the SHA-256 hex digest of that envelope's
  canonical JSON; `compute_digest`, used to represent a large input/output as a fixed-size
  digest in a payload instead of embedding it whole. `format_timestamp` normalizes a
  `created_at` to a stable ISO-8601 UTC string for hashing — including the case where
  SQLite has already dropped the value's `tzinfo` on a fresh read (a value with no
  `tzinfo` here is always treated as already-UTC, never local time, since every
  `created_at` this application produces originates from `datetime.now(UTC)`).
- `service.py` — `append_event`, the *only* way an `AuditEvent` is ever created (nothing
  updates or individually deletes one afterward): allocates the next sequence number,
  links to the previous event's hash (or `GENESIS_HASH` for the first), and retries a
  bounded number of times only on a genuine sequence-number race, re-raising rather than
  silently dropping an event if every retry is exhausted. Rejects an oversized payload
  with `ValueError` — callers must summarize or digest large values, never embed them
  whole. `list_events` returns a workflow's events in sequence order, bounded by `limit`
  (max 500).
- `verification.py` — `verify_event_sequence` (pure logic over an already-fetched event
  list — deliberately separated from database access so tests can feed it deliberately
  malformed, unpersisted histories) and `verify_chain` (the database-backed wrapper):
  confirm sequence numbers are contiguous from `1`, each event's `previous_hash` matches
  the prior event's `event_hash` (`GENESIS_HASH` for the first), and each event's own
  `event_hash` still matches its recomputed hash — stopping at, and reporting, the first
  broken event. `build_provenance` combines a workflow's ordered events with its chain
  validity into one response.

Audit events are appended immediately after the state transition that produced them
commits — never before, and never for a transition that didn't actually commit — but
this is **best-effort sequential coupling, not single-transaction atomicity**: the state
transition and its audit event are two separate commits.

### Known limitations (by design, for this prototype)

- No digital signature, external notarization, or write-once storage backs the chain —
  anyone with direct database write access and the ability to recompute the full chain
  from a modification point onward could rewrite it undetected. Verification only
  detects tampering that does *not* also recompute every subsequent hash.
- Python's standard-library `hashlib.sha256` is sufficient to demonstrate tamper
  evidence for a local SQLite audit log; the `cryptography` package (asymmetric
  signing) is intentionally not a dependency.
- Verification stops at the first invalid event rather than collecting every
  subsequent discrepancy.

## Data storage

SQLite is used as the workflow-state store for this prototype (`sqlite:///./keystone.db`),
configured via `DATABASE_URL`. This keeps the prototype free of external infrastructure
dependencies; it is not intended to be the storage engine for a production deployment.

## Local CLI authentication assumption

Keystone assumes the operator already has working, authenticated local CLI sessions
for whichever providers they enable (subscription-based login — `claude`, `codex`,
`gemini`), managed entirely by those CLIs. Keystone never stores, reads, or logs
credentials; never automates a provider login; and never installs a CLI. `available`
in the agent-availability API means only "the executable resolves on `PATH`" — it does
not prove authentication is valid, since that can only be confirmed by an actual
execution.

## Explicitly out of scope for this prototype

- Kubernetes or any container orchestration beyond Docker Compose
- Distributed databases or message brokers
- Paid third-party APIs (all agent execution is via local, subscription-authenticated
  CLIs — Keystone never calls a provider's HTTP API)
- Self-learning RAG and manager-agent task decomposition
- LangGraph or any other external workflow-graph framework
- OpenTelemetry or other external observability/tracing integration
- Multi-user authentication and Supabase
- Distributed (multi-process/multi-node) execution
- Digital signatures or external notarization of the audit chain, and encryption of
  secrets at rest (see "Known limitations" above)
- Cloud deployment
