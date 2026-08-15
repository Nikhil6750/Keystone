# Keystone AI: Adaptive Multi-Agent Orchestration Platform

## Purpose

Keystone orchestrates work across multiple, provider-neutral coding agents. A goal is
decomposed into a task graph, agents are selected for each task, execution is retried and
recovered on failure, results are verified by an automated Software Quality Factory, and
the outcome is projected into an Engineering Intelligence Graph for reliability/failure
history — all backed by a tamper-evident, hash-linked audit log.

## Current state

This is a working prototype/release candidate, not a finished product. The backend
implements the full pipeline below and is covered by an extensive automated test suite;
the frontend is a functional Next.js app wired to the real backend APIs (not mock data).

```text
Goal
  -> Task Graph compilation
  -> Agent Organization (selection across connected, provider-neutral agents)
  -> Verified Skill Foundry enrichment (where a matching skill exists)
  -> Execution (real local CLI adapters, or the deterministic demo adapter)
  -> Recovery / retry on failure
  -> Software Quality Factory verification (gates: tests/lint/type-check/build)
  -> Engineering Intelligence Graph projection (reliability, failure attribution)
  -> Persisted result, retrievable via the API and shown in the frontend
```

## Repository structure

```text
Keystone/
├── backend/             FastAPI backend (Python 3.12)
│   ├── app/
│   │   ├── api/routes/    REST endpoints (workflows, orchestrations, agents,
│   │   │                  agent-connections, runtime-connections, skills,
│   │   │                  quality, intelligence, audit, resilience, health)
│   │   ├── adapters/      Local CLI agent adapters (Claude Code, Codex, Gemini,
│   │   │                  Antigravity) + the deterministic demo adapter
│   │   ├── audit/         Hash-linked, tamper-evident audit log
│   │   ├── engine/        Orchestration, planning, routing, skills, quality,
│   │   │                  intelligence, workflow execution, resilience
│   │   ├── models/        SQLAlchemy ORM models
│   │   └── schemas/       Pydantic request/response schemas
│   └── tests/            pytest test suite (2400+ tests)
├── frontend/             Next.js 15 / React 19 / Tailwind app
├── vscode-extension/      Separate VS Code extension product (not wired to the
│                          backend yet; not part of the web app flow below)
├── docs/                 Architecture and API contract documentation
└── .github/workflows/    CI (lint, type check, test)
```

## Backend setup

Requires Python 3.12+ and `uv`.

```bash
cd backend
uv sync --frozen
cp .env.example .env
uv run uvicorn app.main:app --reload
```

The API is served at `http://localhost:8000` (`GET /api/v1/health` for a liveness check).

### Backend tests / lint / typecheck

```bash
cd backend
uv run pytest -q
uv run ruff check .
uv run mypy app
```

## Frontend setup

Requires Node.js (the frontend was developed and verified against the toolchain pinned in
`frontend/package.json`/`package-lock.json` — works on Windows, macOS, and Linux; native
`@next/swc-*` platform binaries are optional npm dependencies that install automatically
for your OS).

```bash
cd frontend
npm install
npm run dev
```

The app is served at `http://localhost:3000` and expects the backend at
`http://localhost:8000` by default. Point it elsewhere with:

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### Frontend tests / lint / typecheck / build

```bash
cd frontend
npm run test:run
npm run lint
npm run typecheck
npm run build
```

## Running without a paid provider

Set `KEYSTONE_DEMO_ENABLED=true` in `backend/.env` (or the environment) to register the
built-in deterministic demo adapter, which makes no network calls and spawns no
subprocess — it always returns the same clearly-labeled `[DEMO] Simulated result...` text.
It is enough to exercise the full pipeline (task graph, agent selection, execution,
recovery, quality gates, intelligence projection) end to end with no external dependency
and no cost. In the Orchestrate page (or via `POST /api/v1/orchestrations`), select the
"Demo Agent" as the available agent.

The backend's own test suite exercises this same full pipeline deterministically —
see `backend/tests/test_e2e_prototype_flow.py`.

## Connecting a real agent/provider

Keystone is provider-neutral: the backend does not assume a fixed list of agents, and the
UI never hardcodes one. Today it genuinely supports:

- **Local CLI runtimes** — Claude Code, Codex, Gemini CLI, Google Antigravity. Keystone
  invokes the CLI already authenticated on the machine running the backend; it never
  receives or stores a password, browser cookie, or API key for these. See
  `backend/.env.example` for the `KEYSTONE_*_ENABLED`/`KEYSTONE_*_EXECUTABLE` settings and
  [`docs/live-agent-connectors.md`](docs/live-agent-connectors.md). The Agents page
  (`/agents`) shows real, truthful installation/authentication/connection status for each
  — never a fabricated "connected" state.
- **Dynamic connected-agent identities** (`/api/v1/agent-connections`,
  `/api/v1/connected-agents`) — register an arbitrary agent identity against a connection
  of kind `installed_runtime`, `api`, `local`, or `custom`. This layer deliberately stores
  no credential/key fields (see `app/engine/connections/models.py`); a real API key or
  token is always sourced from the backend process's own environment, never entered
  through the UI or persisted by Keystone.
- **The demo adapter** — see above.

What is **not** currently implemented: a built-in OpenAI-compatible/OpenRouter HTTP
executor, or a generic BYOK API-key execution path. The `api`/`custom`/`local` connection
*kinds* exist as data (you can register the identity), but there is no adapter that
actually executes against them yet — do not present that as working execution support.

## Known limitations

- The frontend's manual, per-step workflow builder (`/chat`) and the automatic full-pipeline
  flow (`/orchestrate`) are two distinct, intentionally separate flows — the former never
  goes through Task Graph/Agent Organization/Skill Foundry/Quality/Intelligence.
- The demo adapter's output is a fixed, minimal stub. It reliably completes execution and
  recovery, but its plain-text response does not satisfy every verification criterion a
  real Planner-generated task graph can attach (e.g. a criterion expecting structured test
  counts) — this can surface as an `inconclusive`/`recovery_exhausted` outcome for the
  demo agent on some goals. This is an honest limitation of a deliberately minimal stub,
  not a false-success bug: no path reports a passing quality/verification result it did
  not actually earn.
- No OpenAI-compatible/OpenRouter/generic BYOK execution adapter yet (see above).
- Single-user, local-only prototype: no authentication, multi-tenant workspace, or
  billing.
- The VS Code extension (`vscode-extension/`) is a separate, not-yet-integrated product;
  the web app in `frontend/` is the supported product surface today.

## Docker Compose

```bash
docker compose up --build
```
