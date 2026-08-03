# Keystone Phase 5 Demo Runbook

This runbook walks through running the full Keystone prototype locally — backend and
frontend together — and demonstrating every Phase 1–5 capability end to end.

## Prerequisites

- Python 3.12+ (backend)
- Node.js 20.19+/22.13+ and npm (frontend) — see `frontend/package.json` engines note
- No external services required: SQLite is the workflow-state store, and the demo agent
  needs no network access or provider credentials

## Backend setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
```

## Frontend setup

```bash
cd frontend
npm ci
cp .env.example .env.local
```

## Required environment variables

Backend (either in `backend/.env` or as process environment variables):

```bash
KEYSTONE_DEMO_ENABLED=true
KEYSTONE_AUTO_COMPENSATE_ON_FAILURE=false
```

Frontend (`frontend/.env.local`):

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Never commit `backend/.env` or `frontend/.env.local` — both are git-ignored. No API key,
password, or provider credential is ever stored by either the backend or the frontend.

## Demo-mode enablement

`KEYSTONE_DEMO_ENABLED=true` registers the `demo` agent type and its `demo.undo`
compensation handler. Neither launches a subprocess or contacts a network — both return
deterministic, clearly-labeled (`metadata.execution_mode: "demo"`) output. This is the
only agent type this runbook's demo scenarios use, so no real provider CLI is required to
follow it end to end.

## CLI login explanation (for real provider agents, optional)

Real Claude Code, Codex, and Gemini execution requires each CLI to be installed and
**authenticated separately on the machine running the backend** — Keystone never installs
a CLI, never automates a login, and never stores or reads a provider credential. The
`/agents` page's `available`/`registered` flags only ever reflect whether the executable
resolves on `PATH`; they never assert that authentication succeeded, since only an actual
execution proves that.

## Starting the servers

Terminal 1 (backend):

```bash
cd backend
KEYSTONE_DEMO_ENABLED=true KEYSTONE_AUTO_COMPENSATE_ON_FAILURE=false uvicorn app.main:app --reload
```

Terminal 2 (frontend):

```bash
cd frontend
npm run dev
```

- Backend: http://localhost:8000
- Frontend: http://localhost:3000

The backend's default `CORS_ORIGINS` already includes `http://localhost:3000` and
`http://127.0.0.1:3000` (see `backend/.env.example`), so no CORS configuration change is
needed for local use.

## Successful workflow demo

1. Open http://localhost:3000 and confirm the header's backend status badge shows the
   real result of `GET /api/v1/health` (not a hardcoded "Connected").
2. Open **Agents** and confirm `demo` shows Enabled / Available / Registered, and the
   other three canonical agent types (`claude_code`, `codex`, `gemini`) show their real,
   current configuration.
3. Open **New Workflow** (`/chat`), start a draft (from the goal box or a template),
   add at least two steps, select `demo` as the agent for each, and click
   **Create Workflow**.
4. Confirm the workflow is created `pending`, then click **Execute**. The button disables
   itself and shows "Execution request in progress." while the request is in flight.
5. Confirm both steps appear, in position order, each `succeeded` with one attempt.
6. Open **Workflows** and confirm the same workflow appears with real status/step counts
   — never a hardcoded row.
7. Open **Logs**, select the workflow, and confirm the event timeline is ordered by
   sequence number and the chain shows **"Tamper-evident audit chain valid."**

## Failure demo

1. Create a workflow with step 0 using `demo` (with `compensation_handler: demo.undo`)
   and step 1 using a currently-disabled/unregistered agent type (e.g. `claude_code`,
   if it isn't enabled in your `.env`).
2. Click Execute. Confirm step 0 succeeds, step 1 fails, and the workflow becomes
   `failed` with a readable error message (no stack trace).

## Retry and circuit-breaker demo

The demo agent never fails, so triggering a live `OPEN` circuit breaker through the
public API requires a real agent configured to fail retryably — this prototype does not
ship a public "always fails" endpoint (that behavior is only exercised by the backend's
own pytest suite, via test-only fakes, e.g. `backend/tests/test_auto_compensation.py`).
To see retry/circuit-breaker behavior live, enable a real provider CLI that is not
authenticated (it will fail with a retryable error) and watch the **Agents** page's
circuit-breaker panel move `closed → open` after `KEYSTONE_CIRCUIT_BREAKER_FAILURE_THRESHOLD`
consecutive failures, along with `failure_count`, `retry_after_seconds`, and
`half_open_probe_in_flight`. There is no reset button — restarting the backend process is
the only reset in this prototype.

## Compensation demo

1. From the failed workflow above, click **Compensate Workflow**.
2. Confirm the confirmation dialog explains reverse-order, best-effort compensation
   before anything runs.
3. Confirm step 0 becomes `compensated`, the workflow becomes `compensated`, a
   compensation attempt appears under step 0, and the compensation summary is shown.
4. Open **Logs** again and confirm the timeline now includes both the original failure
   and the compensation events, in order, and the chain is still valid.

## Audit verification demo

Already exercised above — every workflow page and the Logs page call
`GET /workflows/{id}/audit-chain/verify` and display **"Tamper-evident audit chain
valid"** (never "tamper-proof").

To see the invalid state: with `KEYSTONE_DEMO_ENABLED=true` and a **disposable** SQLite
file (never the file backing real data), directly edit one `audit_events.payload` row,
then refresh **Logs** for that workflow. The chain now shows **"Audit chain invalid"**
with the correct `first_invalid_sequence` and reason. Delete the disposable database file
afterward — never modify a database you want to keep.

## Provenance demo

Also exercised above — the **Logs** page's event timeline is `GET
/workflows/{id}/provenance`'s `events`, always rendered in ascending `sequence_number`
order, with each event's actor, correlated step/attempt IDs, timestamp, and (behind a
`<details>` disclosure) its canonical payload and hash chain.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| Header shows "Backend: Unreachable" | Backend isn't running, or `NEXT_PUBLIC_API_URL` doesn't match its actual address |
| `npm ci` fails with `EBADPLATFORM` | Should not happen after this Phase 5 fix — if it recurs, check `frontend/package.json` for a re-added platform-specific `@next/swc-*` dependency |
| Agent shows `enabled: true` but `available: false` | The configured executable isn't on `PATH` on the machine running the backend |
| Execute returns `503 AGENT_EXECUTOR_NOT_REGISTERED` | The step's `agent_type` isn't enabled/registered in the running backend — check `backend/.env` |
| Compensate returns `409 INVALID_COMPENSATION_STATE` | The workflow isn't currently `failed` — this includes `succeeded`, which can never be manually compensated |
| Compensate returns `503 COMPENSATION_HANDLER_NOT_REGISTERED` | An eligible step's `compensation_handler` name has no registered handler (only `demo.undo` exists in this prototype, and only when demo mode is enabled) |

## Known prototype limitations

- Single-user, local-only — no authentication, no multi-user workspace.
- Synchronous execution only — no background jobs, no WebSockets/SSE, no live streaming.
- No automatic task decomposition or agent selection — the user manually builds every
  step and picks every agent (Phase 6).
- No Knowledge/RAG, vector database, or external knowledge API (Phase 7).
- Circuit-breaker state is in-memory only and resets when the backend process restarts;
  there is no reset endpoint.
- The audit chain is tamper-**evident**, not tamper-proof — no digital signature or
  external notarization backs it.
- Compensation is best-effort reversal, not a distributed transaction — a handler that
  appears to succeed is not provably a full reversal of every external side effect.
