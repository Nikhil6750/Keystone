# Keystone Core Contracts

Canonical, provider-neutral domain contracts for the Keystone workflow engine,
routing, agent passports, Obsidian knowledge backend, and benchmarking. This
is the shared vocabulary Developer 2 (VS Code extension / webview) and
Developer 3 (CLI, provider connectors) build against.

## Ownership

Developer 1 (backend core engine) owns everything in this document: the
Python/Pydantic models under `backend/app/contracts/`, and the generated JSON
Schema artifacts under `backend/contracts/schemas/`. The Python/Pydantic
model is always the canonical definition; the generated JSON Schema is a
derived, machine-readable artifact for non-Python consumers. Nobody
hand-writes a second incompatible copy of these shapes.

## Dependency direction

```
Extension / CLI  (Developer 2 / Developer 3)
      |
      v
Backend APIs            (app/api/)
      |
      v
Application services    (app/services/, app/engine/)
      |
      v
Domain contracts         <-- app/contracts/  (this document)
      |
      v
Persistence and provider interfaces  (app/models/, app/adapters/)
```

`app/contracts/` sits below the API and service layers and above persistence:
it has no dependency on FastAPI, SQLAlchemy sessions, or any concrete
provider adapter. It imports only `app.models.enums` (the two persisted
status enums, `WorkflowStatus`/`StepStatus`) and `app.schemas.errors`
(`APIErrorEnvelope`, reused as `ErrorResponse` rather than redefined).

## What's additive vs. what's live today

This stage does not change any currently-shipping behavior:

- `app/schemas/*` (the live `WorkflowCreate`/`WorkflowRead`/etc. API contract)
  and the position-ordered `Workflow`/`WorkflowStep` ORM models are
  unchanged. `app/contracts/workflow.py` adds a new, additive
  `WorkflowDefinition`/`WorkflowStepDefinition` shape with a `depends_on`
  graph on top — Stage 2 wires this into a real DAG scheduler.
- `app/engine/executor.py`'s synchronous `AgentExecutor` protocol, which the
  live `WorkflowEngine` calls today, is unchanged. `app/contracts/adapter.py`
  adds a new, additive asynchronous `AgentAdapter` protocol (`describe`,
  `capabilities`, `verify`, `health`, `execute`, `cancel`) for Developer 3's
  vNext connectors; provider-specific detail stays inside each request/result's
  optional `metadata` field, never as a first-class contract field.
- Routing, agent passports, the Obsidian knowledge backend, and benchmarking
  have no prior implementation — their contracts here are genuinely
  greenfield, defined ahead of the logic that will produce and consume them
  in Stages 4 through 7.

## Contract catalog

| Contract | Module | Purpose |
|---|---|---|
| `AgentAdapter` | `app/contracts/adapter.py` | Provider-neutral connector protocol |
| `AgentDescriptor` | `app/contracts/adapter.py` | Static agent identity + capabilities |
| `AgentExecutionRequest` | `app/contracts/adapter.py` | One `execute()` call's input |
| `AgentExecutionResult` | `app/contracts/adapter.py` | One `execute()` call's outcome |
| `AgentUsage` | `app/contracts/adapter.py` | Optional token/cost usage |
| `RepositoryMetadata` | `app/contracts/adapter.py` | Non-sensitive repo context |
| `WorkflowDefinition` | `app/contracts/workflow.py` | DAG-aware workflow definition |
| `WorkflowStepDefinition` | `app/contracts/workflow.py` | One DAG node + its `depends_on` |
| `WorkflowExecutionEvent` | `app/contracts/workflow.py` | One timeline event, for audit/SSE |
| `WorkflowStatus` / `WorkflowStepStatus` | re-exported from `app.models.enums` | Persisted state enums |
| `RoutingRequest` | `app/contracts/routing.py` | A request to select an agent |
| `RoutingCandidateScore` | `app/contracts/routing.py` | One candidate's evaluated fitness |
| `RoutingDecision` | `app/contracts/routing.py` | An explainable routing outcome |
| `AgentPassport` | `app/contracts/passports.py` | Objective, outcome-based evidence profile |
| `AgentPassportMetricBucket` | `app/contracts/passports.py` | Per-dimension metric slice |
| `KnowledgeDocument` | `app/contracts/knowledge.py` | One indexed vault document |
| `KnowledgeSearchResult` | `app/contracts/knowledge.py` | One vault search hit |
| `BenchmarkDefinition` | `app/contracts/benchmark.py` | A reproducible agent comparison |
| `BenchmarkTask` | `app/contracts/benchmark.py` | One task within a benchmark |
| `BenchmarkResult` | `app/contracts/benchmark.py` | One agent/task/attempt outcome |
| `FailureCategory` | `app/contracts/errors.py` | Standardized failure taxonomy |
| `ErrorResponse` | `app.schemas.errors.APIErrorEnvelope` (reused, not redefined) | API error envelope |

## Explainability and evidence rules encoded in the contracts

- `AgentExecutionResult` requires a `failure_category` whenever `status` is
  `FAILED` — every failure must be classifiable, not just a free-text message.
- `RoutingDecision.explanation` must be non-blank — routing is never a black
  box (see rule 20 in the build plan).
- `RoutingCandidateScore` and `AgentPassport` leave score/latency fields
  `None` rather than defaulting to a high score when historical data is
  missing, and carry an explicit `low_sample_size` flag — missing data is
  never silently treated as perfect performance.
- No contract in this catalog defines a credential, token, password, or
  session field (enforced by
  `tests/test_contracts_serialization.py::test_no_contract_model_defines_a_credential_shaped_field`).

## Generated JSON Schema

Regenerate after any contract model change:

```
cd backend
python scripts/export_contracts.py
```

This writes one `<ModelName>.schema.json` file per entry in
`app.contracts.schema_export.CONTRACT_MODELS` into
`backend/contracts/schemas/`. `tests/test_contracts_schema_export.py` fails
CI if a committed schema file is stale relative to its model.

## For Developer 2 (extension / webview)

Build mock Webview objects directly from `backend/contracts/schemas/*.schema.json`
— every field, type, and enum value used by the routing, passport, knowledge
and benchmark UIs will eventually flow through is already defined here, even
before the corresponding backend logic exists.

## For Developer 3 (CLI / provider connectors)

Implement new connectors against the `AgentAdapter` protocol in
`app/contracts/adapter.py`. The current live connectors in
`backend/app/adapters/` implement the older synchronous `AgentExecutor`
protocol and are unaffected by this stage; note this repo currently has no
separate `cli/`/`extension/` split — see the Stage 1 completion report for
that ownership-boundary discrepancy.
