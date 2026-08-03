# Keystone Backend Build Plan

This document tracks the same-day prototype build across phases. Only phases marked
`COMPLETE` have working, tested code behind them; `PLANNED` phases describe intended
design only.

## Phase 1: Workflow state and SQLite persistence — `COMPLETE`

Implemented:

- SQLAlchemy 2.x database setup (`backend/app/database/base.py`, `session.py`, `init_db.py`)
- `Workflow`, `WorkflowStep`, `StepAttempt` models (`backend/app/models/`)
- `WorkflowStatus`, `StepStatus`, `AttemptStatus` enums (`backend/app/models/enums.py`)
- State-transition validation (`backend/app/engine/state_machine.py`)
- Workflow persistence service (`backend/app/services/workflow_service.py`)
- Explicit database initialization, wired into the existing FastAPI lifespan
- Unit tests covering the database layer, schemas, state machine, and service

## Phase 2: Workflow API and execution engine — `COMPLETE`

Implemented:

- Workflow REST API: `POST /api/v1/workflows`, `GET /api/v1/workflows/{id}`,
  `GET /api/v1/workflows`, `POST /api/v1/workflows/{id}/execute`
  (`backend/app/api/routes/workflows.py`)
- `{"error": {"code", "message", "details"}}` error envelope, mapping domain
  exceptions and FastAPI validation errors to `404`/`409`/`422`/`503`/`500`
  (`backend/app/api/errors.py`, `backend/app/schemas/errors.py`)
- Synchronous, sequential `WorkflowEngine` (`backend/app/engine/workflow_engine.py`):
  resolves executors, transitions steps/workflow through the existing state
  machine, persists attempt history, aggregates step outputs on success, and
  persists a safe failure state (without retry) on an unregistered executor or
  an expected step failure
- `AgentExecutor` protocol and `StepExecutionRequest`/`StepExecutionError`
  (`backend/app/engine/executor.py`)
- In-process `ExecutorRegistry`, owned per-application via FastAPI lifespan
  state — not a module-level singleton (`backend/app/engine/registry.py`)
- Immutable `ExecutionContext` threading step outputs by stable step ID
  (`backend/app/engine/context.py`)
- `workflow_service.set_workflow_result` for persisting aggregated
  output/error without bypassing the state machine
- Comprehensive tests: API routes, registry, execution context, engine
  success/failure paths, and transaction-boundary behavior

No real agent executors are registered — `POST .../execute` returns `503` for
any workflow with at least one step until Phase 3.

## Phase 3: Agent adapters and resilience — `PLANNED`

- Base agent adapter contract
- Claude Code adapter
- Codex adapter
- Gemini adapter
- Local mock adapter
- Retry policies
- Circuit breaker

## Phase 4: Compensation and audit — `PLANNED`

- Saga compensation
- Reverse-order compensation
- Hash-linked audit events
- Audit-chain verification
- Failure recovery

## Phase 5: Integration and demonstration — `PLANNED`

- Frontend integration
- End-to-end workflow test
- Failure demonstration
- Retry demonstration
- Circuit-breaker demonstration
- Compensation demonstration
- Audit verification
