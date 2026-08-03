# Keystone AI — Architecture

This document describes the intended module layout for the Keystone backend. It reflects
the target design, not the current implementation state — see the "Implementation status"
note under each module.

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
**Implementation status: partially implemented.** `api/routes/health.py` (root/health),
`api/routes/workflows.py` (create/get/list/execute workflows), `api/routes/agents.py`
(`GET /agents`), and `api/routes/resilience.py` (`GET /resilience/circuit-breakers`) exist.
`api/deps.py` provides the request-scoped `WorkflowEngine`/`ExecutorRegistry`/
`CircuitBreakerRegistry`/`RetryPolicy` dependencies, each reading its application-scoped
instance from `request.app.state`; `api/errors.py` maps domain exceptions (including
`CircuitBreakerOpenError` → `503 CIRCUIT_BREAKER_OPEN`) and FastAPI validation errors to
the `{"error": {...}}` envelope (see api-contract.md). No compensation or audit endpoints
exist yet.

### `schemas/`
Pydantic models defining request and response shapes for the API layer.
**Implementation status: partially implemented.** `schemas/health.py`,
`schemas/workflow.py` (`WorkflowCreate`, `WorkflowStepCreate`, `WorkflowRead`,
`WorkflowStepRead`, `StepAttemptRead`, `WorkflowListResponse`), `schemas/errors.py`
(`APIErrorCode`, `APIError`, `APIErrorEnvelope`), `schemas/agents.py`
(`AgentAvailabilityRead`, `AgentAvailabilityListResponse`), and `schemas/resilience.py`
(`CircuitBreakerRead`, `CircuitBreakerListResponse`) exist and back the API routes.

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
**Implementation status: implemented** for workflow state. `models/enums.py` defines
`WorkflowStatus`, `StepStatus`, and `AttemptStatus`. `models/workflow.py` defines
`Workflow` (the top-level orchestration unit, versioned, with an ordered `steps`
relationship). `models/workflow_step.py` defines `WorkflowStep` (one ordered, retryable
unit of work per workflow, unique by `(workflow_id, position)`). `models/step_attempt.py`
defines `StepAttempt` (retained execution-attempt history per step, unique by
`(step_id, attempt_number)`). Deleting a workflow cascades to its steps and attempts at
both the ORM and database level.

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

Saga-style compensation is not yet implemented.

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
**Implementation status: partially implemented.** `services/workflow_service.py`
implements workflow/step/attempt persistence: `create_workflow` (workflow plus its
ordered steps in one transaction, rolled back entirely on failure), `get_workflow`,
`list_workflows`, `transition_workflow`, `transition_step`, `create_step_attempt`,
`complete_step_attempt`, and `set_workflow_result` (persists a workflow's aggregated
`output_payload` and/or `error_message` without changing its status — used by
`WorkflowEngine` to record execution results). Each state-changing operation persists
through the state machine in `engine/state_machine.py` within a single transaction,
rolling back and re-raising on invalid transitions or database errors.
`services/agent_availability.py` reports each canonical agent type's
enabled/available/registered status and a safe reason string (never an absolute
executable path or CLI arguments) for `GET /api/v1/agents`.
`WorkflowEngine` (`engine/workflow_engine.py`) is the higher-level orchestration
service for execution; saga-style compensation is not yet implemented.

### `audit/`
A hash-linked, append-only log of workflow and agent events, so that after-the-fact
audits can detect tampering (each event's hash incorporates the previous event's hash).
**Implementation status: not implemented.**

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
- Saga-style compensation and hash-linked audit logging (pending future implementation
  steps)
