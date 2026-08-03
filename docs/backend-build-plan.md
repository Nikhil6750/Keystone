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

## Phase 2: Workflow API and execution engine — `PLANNED`

- Workflow creation API
- Workflow status API
- Workflow listing API
- Step execution sequencing
- Execution context
- Workflow result aggregation

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
