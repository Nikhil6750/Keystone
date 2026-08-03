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
**Implementation status: partially implemented.** Only the root and health endpoints exist
so far (`api/routes/health.py`).

### `schemas/`
Pydantic models defining request and response shapes for the API layer.
**Implementation status: partially implemented.** Only `schemas/health.py` exists so far.

### `database/`
SQLAlchemy engine/session setup and persistence of workflow state to SQLite.
**Implementation status: not implemented.** Directory exists as a placeholder package.

### `models/`
SQLAlchemy ORM models representing workflows, steps, and agent invocations.
**Implementation status: not implemented.**

### `engine/`
The workflow orchestration engine: sequencing steps, tracking workflow state, and
invoking agents through adapters.
**Implementation status: not implemented.**

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
**Implementation status: not implemented.**

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
