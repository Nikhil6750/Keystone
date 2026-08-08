"""DAG-aware workflow graph and concurrent scheduler (Stage 2).

Additive engine capability layer, built against the Stage 1
`WorkflowDefinition`/`WorkflowStepDefinition` contracts
(`app.contracts.workflow`). It does not touch the live, position-ordered,
synchronous `WorkflowEngine` (`app.engine.workflow_engine`) or the persisted
`Workflow`/`WorkflowStep` ORM models — wiring this scheduler into persistence
and the `/workflows` API is deferred pending a schema-migration and
API-contract decision (see `docs/architecture.md`).
"""
