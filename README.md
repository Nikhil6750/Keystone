# Keystone AI: Fault-Tolerant Orchestration for Multi-Agent LLM Systems

## Purpose

Keystone AI orchestrates workflows across multiple LLM agents while tolerating individual
agent failures. Failed steps are retried, circuit-broken, or compensated for rather than
taking down the whole workflow, and every state transition is recorded in a tamper-evident,
hash-linked audit log.

## Prototype scope

This repository currently contains a **same-day prototype foundation**: repository
structure, a minimal FastAPI backend with health/root endpoints, configuration, logging,
CORS, tests, linting, type checking, and CI. It intentionally does **not** yet include
workflow orchestration, agent adapters, retry policies, circuit breakers, saga-style
compensation, or audit logging — see [`docs/architecture.md`](docs/architecture.md) for the
intended design and current implementation status of each module.

The prototype avoids Kubernetes, distributed databases, message brokers, and paid APIs.
SQLite is used as the workflow-state store; Docker Compose is available for local runs.

## Live agent connectors

Keystone can execute workflow steps through real, locally installed coding-agent CLIs
(Claude Code, Codex, Google Antigravity) in addition to the built-in demo agent — see
[`docs/live-agent-connectors.md`](docs/live-agent-connectors.md). Keystone does not
receive provider passwords, browser cookies, OAuth refresh tokens, or API keys. It
invokes locally installed provider CLIs that are already authenticated under the
backend operating-system user.

## Repository structure

```text
Keystone/
├── backend/            FastAPI backend (Python 3.12)
│   ├── app/
│   │   ├── api/routes/  REST endpoints
│   │   ├── adapters/    Agent integrations (not yet implemented)
│   │   ├── audit/       Hash-linked audit log (not yet implemented)
│   │   ├── core/        Settings and logging
│   │   ├── database/    SQLAlchemy engine/session (not yet implemented)
│   │   ├── engine/      Workflow orchestration engine (not yet implemented)
│   │   ├── models/      SQLAlchemy ORM models (not yet implemented)
│   │   ├── resilience/  Retry policies and circuit breakers (not yet implemented)
│   │   ├── schemas/     Pydantic request/response schemas
│   │   └── services/    Application services (not yet implemented)
│   └── tests/           pytest test suite
├── frontend/            React/Next.js frontend (not yet started)
├── docs/                Architecture and API contract documentation
├── prompts/             Agent prompt templates (not yet populated)
└── .github/workflows/   CI (lint, type check, test)
```

## Backend setup

Requires Python 3.12+ and `uv`.

```bash
cd backend
uv sync --frozen
cp .env.example .env
```

## Running tests

```bash
cd backend
uv run pytest -q
```

## Linting and type checking

```bash
cd backend
uv run ruff check app tests
uv run mypy app
```

## Starting the API

```bash
cd backend
uvicorn app.main:app --reload
```

The API is served at `http://localhost:8000`:

- `GET /` — service info
- `GET /api/v1/health` — health check

Alternatively, with Docker Compose:

```bash
docker compose up --build
```
