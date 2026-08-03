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
**Implementation status: partially implemented.** `api/routes/health.py` (root/health) and
`api/routes/workflows.py` (create/get/list/execute workflows) exist. `api/deps.py`
provides the request-scoped `WorkflowEngine`/`ExecutorRegistry` dependencies; `api/errors.py`
maps domain exceptions and FastAPI validation errors to the `{"error": {...}}` envelope
(see api-contract.md). No retry, compensation, or audit endpoints exist yet.

### `schemas/`
Pydantic models defining request and response shapes for the API layer.
**Implementation status: partially implemented.** `schemas/health.py`,
`schemas/workflow.py` (`WorkflowCreate`, `WorkflowStepCreate`, `WorkflowRead`,
`WorkflowStepRead`, `StepAttemptRead`, `WorkflowListResponse`), and `schemas/errors.py`
(`APIErrorCode`, `APIError`, `APIErrorEnvelope`) exist and back the workflow API routes.

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
- On an *expected* step failure (`StepExecutionError`) or a missing executor
  (`ExecutorNotRegisteredError`), persists the step/attempt/workflow as `FAILED` with a
  safe error message, and stops — later steps are left `PENDING`, not retried. A missing
  executor re-raises (mapped to `503` by the API layer); an expected step failure returns
  the persisted `FAILED` workflow normally (`200` at the API layer — a step failure is
  normal workflow execution, not an API error). Unexpected exceptions are also persisted
  as a sanitized `FAILED` state, logged with full detail server-side, and re-raised
  (mapped to `500`).
- `engine/exceptions.py` defines `WorkflowNotFoundError` and `InvalidWorkflowStateError`,
  raised before execution starts (missing workflow / not `PENDING`) and shared with the
  API's `GET /workflows/{id}` route.

Retries, circuit breakers, and saga-style compensation are not yet implemented.

### `adapters/`
Thin integration layers between the orchestration engine and individual LLM agents
(e.g., calling out to an agent's API and normalizing its response).
**Implementation status: not implemented.**

### `resilience/`
Retry policies and circuit breakers applied around agent adapter calls, so transient
agent failures don't cascade into workflow failures.
**Implementation status: not implemented.**

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

## Explicitly out of scope for this prototype

- Kubernetes or any container orchestration beyond Docker Compose
- Distributed databases or message brokers
- Paid third-party APIs
- Agent execution, retries, circuit breakers, saga-style compensation, and audit logging
  (all pending future implementation steps)
