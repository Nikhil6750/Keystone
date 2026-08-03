# Phase 5: Frontend Integration

This document describes how the Next.js frontend (merged in PR #6) was wired to the real
Keystone backend, replacing every mock/fixed-pipeline behavior with real API integration.
It complements [`architecture.md`](./architecture.md) (backend design) and
[`api-contract.md`](./api-contract.md) (the API surface both sides agree on).

## Frontend framework

Next.js 15.5.22 (App Router), React 19.1.0, TypeScript ~5, Tailwind CSS v4, npm. The
`@next/swc-darwin-arm64` package that previously made `npm ci` fail on Windows/Linux was
removed from direct `dependencies` in `frontend/package.json` — Next.js now resolves its
own platform-specific SWC binary as an ordinary optional dependency, exactly as intended.

## API client architecture

- `services/api-client.ts` — `apiRequest<T>()`, the single typed request boundary every
  service module calls. Configurable base URL (`NEXT_PUBLIC_API_URL`, trailing slash
  stripped once in `lib/constants.ts`), JSON request/response handling, `AbortSignal`
  support with a combined caller-signal + internal timeout (15s default), and correct
  parsing of the backend's real `{"error": {"code","message","details"}}` envelope into
  a typed `ApiClientError` (`code`/`message`/`details`/`status`). Never retries
  automatically — retry semantics belong to the backend's resilience layer, not the
  browser. Network failures, timeouts, and unparseable responses each get their own
  synthetic `code` (`NETWORK_ERROR`/`TIMEOUT`/`PARSE_ERROR`) so callers can distinguish
  "backend said no" from "couldn't reach the backend."
- `services/{health,workflows,agents,resilience,audit}.ts` — one focused module per
  backend resource, each a thin wrapper around `apiRequest` with no duplicated fetch
  logic. No endpoint beyond the eleven documented in `api-contract.md` was invented (no
  delete-workflow, agent registration, provider login, circuit-breaker reset, chat
  completion, or streaming endpoint exists).
- `types/backend.ts` — TypeScript types copied verbatim from the backend's Pydantic
  schemas (field names, enum values). The previous `ApiResponse<T>`/`PaginatedResponse<T>`/
  `ApiError` types assumed a `data`/`success`/`message` wrapper and a `{items, total,
  page, limit, totalPages}` pagination shape that the real backend has never returned —
  both were removed. `WorkflowStatus`/`StepStatus`/etc. use the exact lowercase wire
  values (`pending`, `succeeded`, `half_open`, ...) — never invented UI-only strings like
  `"Waiting"` or `"Completed"`.
- `lib/presentation.ts` — the *only* place a backend value is mapped to a display label
  or color. `workflowStatusLabel`/`stepStatusLabel`/`circuitBreakerStateLabel` and their
  `*Tone` counterparts are total maps (cover every enum member), so a new backend status
  can never silently render as `undefined`. The wire value itself is never altered.
- `hooks/use-*` — one small hook per resource (`use-backend-health`, `use-workflows`,
  `use-workflow`, `use-agents`, `use-circuit-breakers`, `use-audit-events`,
  `use-provenance`, `use-audit-chain-verification`), all built on a shared internal
  `use-async-resource` helper (plain `useState`/`useEffect`, not a new state-management
  library) that cancels its in-flight request on unmount/dependency change and guards
  against setting state after unmount.

## Screen-to-endpoint mapping

| Screen | Endpoints used |
| --- | --- |
| Header (all pages) | `GET /api/v1/health` |
| `/chat` (New Workflow) | `POST /api/v1/workflows`, `POST /api/v1/workflows/{id}/execute`, `POST /api/v1/workflows/{id}/compensate` |
| `/workflows` | `GET /api/v1/workflows`, plus execute/compensate on the selected workflow |
| `/agents` | `GET /api/v1/agents`, `GET /api/v1/resilience/circuit-breakers` |
| `/logs` | `GET /api/v1/workflows`, `GET /api/v1/workflows/{id}/provenance`, `GET /api/v1/workflows/{id}/audit-chain/verify` |
| `/settings` | `GET /api/v1/health`, `GET /api/v1/agents` |
| Sidebar (Recent Workflows) | `GET /api/v1/workflows?limit=5` |

## Workflow builder behavior (`components/workflow/workflow-builder.tsx`)

A fully manual editor for `name`, `description`, `input_payload` (JSON), and an ordered
list of steps (`name`, `agent_type`, `input_payload`, `max_attempts`,
`compensation_handler`). Validation before submission: name required, step name
required, `max_attempts >= 1`, JSON payload must parse to a plain object, an agent must
be selected from the real `GET /api/v1/agents` list (an unregistered agent is still
selectable but shown with an explicit warning, never silently blocked, since the backend
itself is the source of truth at execution time). The submitted `WorkflowCreate` payload
never includes `id`, `status`, `attempt_count`, `version`, timestamps, or any
process/executable/CLI/environment field — those are either server-assigned or entirely
out of the client's control.

## Manual agent assignment

There is no automatic planning or agent-selection step anywhere in the frontend. The
`/chat` page's own copy says so explicitly ("Automatic planning and agent routing are
coming in Phase 6") and the six static templates under `lib/templates/` only pre-fill
suggested steps/agents for the user to review and edit — never auto-submitted.

## Synchronous execution behavior

`POST .../execute` and `POST .../compensate` are both synchronous HTTP calls — the
frontend disables the triggering button and shows an in-flight message
("Execution request in progress." / "Compensating…") for the duration of the request,
then re-renders the returned, persisted `WorkflowRead`. There is no polling, no
WebSocket, no Server-Sent Events, and no simulated/animated step progress — every
rendered step status is the backend's actual persisted state at the moment the response
arrived.

## Retry display

Retry history is never a live animation — it is the persisted `StepAttemptRead[]` under
each step, rendered after the (already-finished, synchronous) execution call returns.

## Circuit-breaker display (`components/resilience/circuit-breaker-list.tsx`)

Renders `GET /api/v1/resilience/circuit-breakers` directly: `closed`/`open`/`half_open`
state (with both a color and a text label, never color alone), failure count vs.
threshold, recovery timeout, and retry-after seconds. No reset control exists, matching
the backend, which has none.

## Compensation experience

`components/workflow/compensate-dialog.tsx` requires an explicit confirmation
("Keystone will run configured compensation handlers ... in reverse order ... best-effort
and may not reverse every external side effect.") before calling
`POST .../compensate`. The button only ever appears for a `failed` workflow
(`lib/presentation.ts`'s `canCompensateWorkflow`) — a `succeeded` workflow can never be
compensated, matching the backend's `compensate_workflow`, which accepts only `FAILED`
and rejects every other status, `succeeded` included, with `409
INVALID_COMPENSATION_STATE`. The button disappears once the workflow is
`compensating`/`compensated`/`cancelled`/`pending`/`running` — it cannot be invoked
twice from the UI, and the backend itself would reject a second call with `409
COMPENSATION_ALREADY_COMPLETED` regardless.

## Audit and provenance experience

`/logs` combines `GET .../provenance` (ordered event timeline) with
`GET .../audit-chain/verify` (the detailed `valid`/`first_invalid_sequence`/`reason`
banner) for the selected workflow. The UI always says **"tamper-evident,"** never
"tamper-proof." Each event's canonical payload and hash pair are shown behind a
`<details>` disclosure, never inline by default, to keep the primary timeline readable.

## Features explicitly deferred

Not implemented in Phase 5, by design:

- Automatic task decomposition or agent routing (Phase 6)
- A manager/orchestrator agent of any kind, including an embedded ChatGPT
- Evidence-grounded workflow memory, retrieval, or adaptive routing (Phase 7) — the
  `/knowledge` page is a static, honest placeholder naming this
- MCP, A2A, OpenTelemetry, sandboxing/isolation, policy controls (Phase 8)
- Failure injection, replay, or benchmarking tooling (Phase 9)
- Multi-user authentication, billing, subscription credits, or provider browser login
- Background/async execution, WebSockets, SSE, or any simulated streaming
- A real search implementation (the header's search box is an honest disabled control
  labeled "Search coming soon")
