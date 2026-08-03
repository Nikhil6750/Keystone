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

## Phase 3: Agent adapters and resilience — `COMPLETE`

Implemented:

- Safe subprocess execution boundary (`backend/app/adapters/process_runner.py`):
  `shell=False`, list arguments, isolated temp working directory, restricted
  environment, timeout and output-size enforcement, sanitized/bounded stderr
- `CLIProfile` and its validating factory `create_cli_profile`
  (`backend/app/adapters/types.py`); typed adapter exceptions carrying a stable
  error code and retryability (`backend/app/adapters/exceptions.py`)
- Shared deterministic prompt builder (`backend/app/adapters/prompt_builder.py`)
  and the shared `LocalCLIAdapter` (`backend/app/adapters/local_cli.py`)
  subclassed by `ClaudeCodeAdapter`, `CodexAdapter`, `GeminiAdapter` — each using
  the operator's own local, already-authenticated CLI session; no paid HTTP
  APIs, no stored credentials
- `DemoAgentAdapter` (`backend/app/adapters/demo.py`): no subprocess, no
  network, disabled by default, clearly self-labeled
- Settings-driven registration (`backend/app/adapters/factory.py`), composed
  once during FastAPI lifespan; never launches a process at startup, never
  fails startup because an optional agent is disabled or unavailable
- Agent-availability service and API: `GET /api/v1/agents`
  (`backend/app/services/agent_availability.py`,
  `backend/app/api/routes/agents.py`)
- Bounded exponential-backoff retry (`backend/app/resilience/retry.py`) and a
  thread-safe, in-memory, per-agent-type circuit breaker with
  CLOSED/OPEN/HALF_OPEN states (`backend/app/resilience/circuit_breaker.py`),
  both integrated into `WorkflowEngine` additively (Phase 2 behavior for
  non-retryable failures is unchanged)
- Circuit-breaker status API: `GET /api/v1/resilience/circuit-breakers`
  (`backend/app/api/routes/resilience.py`)
- `CIRCUIT_BREAKER_OPEN` → `503` added to the error envelope
- Comprehensive tests (process runner, CLI profile validation, adapters, demo
  adapter, availability, retry policy, circuit breaker, engine retry/circuit
  integration, API) — all using fakes; no automated test launches a real
  provider process
- Manually verified: local `claude` CLI detected (v2.1.154; `-p`/
  `--output-format json` confirmed via `--help`); `codex`/`gemini` not
  installed in this environment, left disabled by default; a demo workflow
  execution (`agent_type=demo`) succeeded end-to-end via the live API; retry
  and circuit-breaker behavior verified end-to-end via the live API using a
  harmless, deterministic local stand-in command (no real provider contacted)

## Phase 4: Compensation and audit — `COMPLETE`

Implemented:

- Saga-style compensation (`backend/app/engine/compensation*.py`,
  `backend/app/models/compensation_attempt.py`): reverses a failed workflow's
  already-successful steps in descending position order, via a per-application
  `CompensationRegistry` (mirroring `ExecutorRegistry`); each handler invocation is
  persisted as a `CompensationAttempt`, unique by `(step_id, attempt_number)`
- Manual compensation API: `POST /api/v1/workflows/{id}/compensate`
  (`backend/app/api/routes/workflows.py`)
- Optional automatic compensation immediately after an execution failure
  (`KEYSTONE_AUTO_COMPENSATE_ON_FAILURE`, default `false`), best-effort and
  never masking the original failure (`backend/app/engine/workflow_engine.py`)
- `DemoCompensationHandler` (`demo.undo`): no subprocess, no network, registered
  only when demo mode is enabled (`backend/app/engine/demo_compensation.py`)
- Tamper-evident SHA-256 hash-chained audit log (`backend/app/audit/`,
  `backend/app/models/audit_event.py`): canonical JSON serialization, genesis hash
  of 64 zero characters, one `AuditEvent` per workflow/step/attempt/compensation
  milestone, append-only
- Audit-chain verification, provenance tracing, and audit-event listing APIs:
  `GET /api/v1/workflows/{id}/audit-chain/verify`,
  `GET /api/v1/workflows/{id}/provenance`,
  `GET /api/v1/workflows/{id}/audit-events` (`backend/app/api/routes/audit.py`)
- `WorkflowRead.compensation_summary` and `WorkflowStepRead.compensation_attempts`
  expose compensation state through the existing workflow API
- New API error codes: `INVALID_COMPENSATION_STATE`,
  `COMPENSATION_HANDLER_NOT_REGISTERED`, `COMPENSATION_EXECUTION_FAILED`,
  `COMPENSATION_ALREADY_COMPLETED` (plus reserved `AUDIT_CHAIN_INVALID`,
  `AUDIT_EVENT_CONFLICT`)
- Comprehensive tests: compensation model/registry/ordering/success/failure,
  manual and automatic compensation APIs, canonical serialization, hashing,
  audit append/verification/provenance, audit APIs, and end-to-end integration
  (execution → failure → compensation → audit chain → tamper detection)
- Manually verified against a live server: a successful two-step demo workflow's
  audit chain and provenance; a failed-then-compensated workflow's reverse-order
  compensation, persisted attempts, and still-valid audit chain; direct tampering
  with one audit event's payload in a disposable database correctly flips
  `audit-chain/verify` to `valid: false` with the correct `first_invalid_sequence`

No self-learning RAG, manager-agent task decomposition, LangGraph, OpenTelemetry,
multi-user authentication, Supabase, distributed execution, digital signatures,
secret encryption, or cloud deployment — all out of scope for this phase (see
`architecture.md`).

## Phase 5: Integration and demonstration — `COMPLETE`

Implemented:

- Fixed the merged frontend's cross-platform install blocker: removed
  `@next/swc-darwin-arm64` from direct `dependencies`; `npm ci` now succeeds on
  Windows/Linux, with Next.js resolving its own platform SWC binary as an optional
  dependency
- Typed API client (`frontend/services/api-client.ts`) and one focused service module
  per backend resource (`health`, `workflows`, `agents`, `resilience`, `audit`), all
  implementing exactly the eleven endpoints in `api-contract.md` — no invented endpoint
- `frontend/types/backend.ts`: TypeScript types mirroring every backend Pydantic schema
  field-for-field, replacing the previous incorrect `ApiResponse`/`PaginatedResponse`/
  `ApiError` wrapper assumptions
- `frontend/lib/presentation.ts`: the single place backend enum values are mapped to
  display labels/colors, never altering the wire value itself
- Real workflow creation, listing, retrieval, execution, and compensation wired into
  `/chat` (manual workflow builder) and `/workflows`
- Dynamic execution panel (`components/workflow/execution-panel.tsx`) rendering a
  workflow's actual `steps` (position order), attempts, compensation attempts, and audit
  chain validity — replacing the previously fixed Planner/Research/Executor/Validator/
  Reporter pipeline entirely
- Real agent availability (`/agents`) and circuit-breaker display
  (`components/resilience/circuit-breaker-list.tsx`), removing the fake "Register Agent"
  flow
- New `/logs` page: real audit-event timeline, audit-chain verification banner
  (tamper-evident, not tamper-proof), and provenance, resolving the previously dead
  sidebar link
- `/workspace` now redirects to `/chat` instead of duplicating it
- New `/knowledge` placeholder page, honestly marked "Coming in Phase 7"
- Settings page rewritten to remove the fake email/workspace ID and fake danger-zone
  actions; now shows real backend health, demo-agent/registered-agent status, and theme
  controls
- Frontend test suite added (Vitest + React Testing Library + jsdom): 40 tests across
  12 files covering the API client, presentation mapping, workflow-builder validation,
  the dynamic execution panel, agents/circuit-breaker/logs/settings/knowledge pages, and
  the `/workspace` redirect and `/logs` route
- Frontend CI workflow (`.github/workflows/frontend-ci.yml`): lint, typecheck, test,
  build on every `frontend/**` change
- Manually verified end to end against a live backend + frontend: backend health and
  agent availability; a successful two-step demo workflow through creation → execution →
  workflows list → logs/provenance; a failed workflow → manual compensation → provenance
  showing both the original failure and the compensation, chain still valid; audit
  tamper detection via a disposable database correctly flipping `audit-chain/verify` to
  invalid with the right `first_invalid_sequence`; and network-failure handling
  (backend stopped, then restarted) without exposing a stack trace

No backend code changes were required — the existing CORS configuration already
permitted the frontend's default origin, and no contract mismatch was found. Backend
test count remains 454 (unchanged); `ruff`, `ruff format --check`, and `mypy` all still
pass.

Still deferred, as intended: automatic task decomposition/agent routing (Phase 6),
evidence-grounded workflow memory and RAG (Phase 7), MCP/A2A/OpenTelemetry/isolation
(Phase 8), and failure-injection/replay/benchmarking tooling (Phase 9).

## Phase 6A.1: Live local provider connectors — `COMPLETE`

Implemented:

- Fifth canonical agent type `antigravity` (`backend/app/adapters/types.py`), added
  purely additively — no rename of, or silent alias to, `gemini`. The DB column
  backing `WorkflowStep.agent_type` is an unconstrained `String(100)`, so this required
  no migration; a persisted `agent_type="gemini"` step still resolves strictly through
  the `gemini` executor, never falling back to `antigravity`
  (`backend/tests/test_agent_type_migration.py`)
- Real, verified Claude Code JSON-envelope parsing (`backend/app/adapters/claude_code.py`)
  and a safe `check_authentication` that reads only the `loggedIn` boolean from
  `claude auth status` — never the email/org ID/org name/subscription type it also
  returns
- Modeled (not live-tested; `codex` was not installed in this environment) Codex
  `exec --json` JSONL event-stream parsing (`backend/app/adapters/codex.py`)
- New, modeled (not live-tested; `agy` was not installed in this environment) Google
  Antigravity adapter (`backend/app/adapters/antigravity.py`)
- Shared connection-state model and cache (`backend/app/adapters/connection.py`):
  three independent statuses (`installation_status`/`authentication_status`/
  `connection_status`) — never collapsed into one boolean — plus an in-process,
  TTL-based `AgentConnectionCache` guarding against duplicate concurrent verifications
- Shared keyword-based error classification (`backend/app/adapters/error_classification.py`)
  and three new non-retryable exceptions (`AgentAuthenticationError`,
  `AgentUsageLimitError`, `AgentPermissionError`) — the existing engine retry/
  circuit-breaker/audit machinery required zero changes to honor them
- New connection-verification service (`backend/app/services/agent_connection.py`,
  `verify_agent`) and API: `POST /api/v1/agents/{agent_type}/verify` — runs one safe,
  backend-owned headless prompt with a fresh, single-use token; never accepts a prompt
  from the caller; `404 AGENT_TYPE_UNKNOWN` / `409 AGENT_VERIFICATION_IN_PROGRESS` added
- `GET /api/v1/agents` extended (existing fields unchanged) with `display_name`,
  `installation_status`, `authentication_status`, `connection_status`, `version`,
  `last_checked_at`, `capabilities`
- Defense-in-depth workspace-root validator (`backend/app/adapters/workspace.py`),
  built but not yet wired into execution — no workflow can specify a working directory
  today
- Frontend: rewritten `/agents` page with four provider cards (Claude Code, OpenAI
  Codex, Google Antigravity, Demo Agent — Gemini shown only as a "not configured"
  placeholder), a "Verify Connection" button (duplicate-click prevention via a
  synchronous in-flight guard, honest in-progress/error states, `aria-live` status),
  the exact required credential-handling disclosure, and provider-specific local login
  instructions (`claude auth login` / `codex login` / run `agy` and complete its
  browser sign-in) shown only while unauthenticated — never a credential input
- Workflow builder (`components/workflow/workflow-builder.tsx`) now disables selecting
  any agent that isn't enabled, registered, installed, authenticated, and connected,
  and links the user to the Agents page to verify it
- Backend tests: 516 passing (up from the Phase 5 baseline of 454); `ruff`,
  `ruff format --check`, and `mypy` all pass
- Frontend tests: 64 passing (up from the Phase 5 baseline of 47); lint, typecheck,
  and `next build` all pass
- **A real bug this phase's live verification caught and fixed**: on Windows,
  `shutil.which("claude")` resolves to an npm `.CMD` batch shim, and passing a
  multi-line prompt (every prompt `PromptBuilder` builds embeds newlines) as a
  trailing CLI argument to a `.cmd`/`.bat` target routes the process through
  `cmd.exe`'s own argument re-parsing, which reliably corrupts it — the first real
  Keystone workflow execution through Claude Code returned "No JSON context was
  included in your message" instead of following the actual instruction. Fixed by
  switching Claude Code's (and, preemptively, Antigravity's, which resolves the same
  way) default `input_mode` from `prompt_argument` to `stdin` — matching what Codex
  and Gemini already defaulted to — which sidesteps command-line parsing entirely.
  Confirmed fixed by re-running the same live workflow after the change (see below).
  Locked in by `backend/tests/test_windows_cmd_shim_argument_safety.py`.

No credential, token, password, OTP, or OAuth flow is ever collected, stored, or
proxied through the browser or the backend — every provider CLI runs already
authenticated under the same OS user account that runs the Keystone backend. No
task decomposition, automatic agent selection, manager-agent routing, agent
marketplace, MCP, A2A, RAG, or parallel/long-running background execution was added —
all out of scope for this phase (see `docs/live-agent-connectors.md`).

Manually verified against a live backend with a disposable SQLite database and all
three real providers enabled: `GET /api/v1/agents` correctly reported `claude_code` as
installed/registered and `codex`/`antigravity` as honestly `not_installed`/
`unavailable` (neither CLI exists in this environment, confirmed via both
`Get-Command` and `which`); `POST /agents/claude_code/verify` returned `connected`,
`authenticated`, version `2.1.154 (Claude Code)`; a real one-step `claude_code`
workflow (`max_attempts=1`) succeeded end to end with output content exactly
`KEYSTONE_CLAUDE_CODE_WORKFLOW_OK`, a valid 7-event audit chain, complete provenance,
and a `closed` circuit breaker with zero failures; the equivalent `codex` and
`antigravity` workflows honestly returned `503 AGENT_EXECUTOR_NOT_REGISTERED` — no
success was faked for either. The disposable database was deleted afterward;
`git status --short` showed no tracked-file changes from the live tests. Claude Code
is the only provider genuinely live-verified in this environment; Codex and Google
Antigravity's adapters are built and unit-tested against modeled fixtures only, and
their real CLIs were never available here to verify against.

## Future roadmap

- **Phase 6A.2:** Searchable agent catalog with guided install/login flows (still no
  credential collection through the browser)
- **Phase 6B:** Manager task decomposition and automatic agent routing
- **Phase 7:** Agent Passports, validated workflow memory, evidence-grounded adaptive
  routing, and RAG
- **Phase 8:** MCP, A2A, OpenTelemetry, isolation, and policy controls
- **Phase 9:** Agent Reliability Lab, failure injection, replay, and benchmarking

None of Phases 6A.2–9 are implemented — this build plan only ever marks a phase
`COMPLETE` once its own tests and manual verification have passed, never in advance.
