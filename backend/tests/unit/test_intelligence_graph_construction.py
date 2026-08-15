"""Stage 9E: graph construction -- canonical nodes/edges, no duplicates, idempotent replay."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.contracts.intelligence import IntelligenceEdgeType, IntelligenceNodeType
from app.database.base import Base
from app.engine.intelligence.builder import EngineeringIntelligenceGraphBuilder
from app.engine.intelligence.graph_repository import InMemoryIntelligenceGraphRepository
from app.models.enums import AttemptStatus, StepStatus, WorkflowStatus
from app.schemas.workflow import WorkflowCreate, WorkflowStepCreate
from app.services import workflow_service


def _make_session_factory() -> Callable[[], Session]:
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _build_workflow_with_retry_then_success(session_factory: Callable[[], Session]) -> str:
    """One workflow, one step, generic-agent-1: attempt #1 fails (retryable
    timeout), attempt #2 succeeds -- exercises Task/Attempt/Agent/Outcome/
    Failure/RecoveryAttempt projection end to end."""
    with session_factory() as session:  # type: ignore[operator]
        workflow = workflow_service.create_workflow(
            session,
            WorkflowCreate(
                name="wf-retry-success",
                steps=[
                    WorkflowStepCreate(
                        name="build feature",
                        position=0,
                        agent_type="generic-agent-1",
                        input_payload={"task_type": "code_generation"},
                        max_attempts=3,
                    )
                ],
            ),
        )
        step = workflow.steps[0]

        workflow_service.transition_workflow(session, workflow.id, WorkflowStatus.RUNNING)
        workflow_service.transition_step(session, step.id, StepStatus.RUNNING)
        attempt1 = workflow_service.create_step_attempt(session, step.id)
        workflow_service.complete_step_attempt(
            session,
            attempt1.id,
            status=AttemptStatus.FAILED,
            error_type="AGENT_TIMEOUT",
            error_message="agent did not respond in time",
        )
        workflow_service.transition_step(session, step.id, StepStatus.RETRYING)
        workflow_service.transition_step(session, step.id, StepStatus.RUNNING)
        attempt2 = workflow_service.create_step_attempt(session, step.id)
        workflow_service.complete_step_attempt(
            session, attempt2.id, status=AttemptStatus.SUCCEEDED, output_payload={"ok": True}
        )
        workflow_service.transition_step(session, step.id, StepStatus.SUCCEEDED)
        workflow_service.transition_workflow(session, workflow.id, WorkflowStatus.SUCCEEDED)
        return workflow.id


def test_graph_construction_creates_canonical_nodes_and_edges() -> None:
    session_factory = _make_session_factory()
    workflow_id = _build_workflow_with_retry_then_success(session_factory)

    repo = InMemoryIntelligenceGraphRepository()
    builder = EngineeringIntelligenceGraphBuilder(repo, session_factory)
    summary = builder.ingest_workflow(workflow_id)

    assert summary.found is True
    assert summary.errors == ()

    workflow_nodes = repo.get_nodes_by_type(IntelligenceNodeType.WORKFLOW)
    task_nodes = repo.get_nodes_by_type(IntelligenceNodeType.TASK)
    agent_nodes = repo.get_nodes_by_type(IntelligenceNodeType.AGENT)
    attempt_nodes = repo.get_nodes_by_type(IntelligenceNodeType.ATTEMPT)
    outcome_nodes = repo.get_nodes_by_type(IntelligenceNodeType.OUTCOME)
    failure_nodes = repo.get_nodes_by_type(IntelligenceNodeType.FAILURE)
    recovery_nodes = repo.get_nodes_by_type(IntelligenceNodeType.RECOVERY_ATTEMPT)

    assert len(workflow_nodes) == 1
    assert len(task_nodes) == 1
    assert len(agent_nodes) == 1
    assert agent_nodes[0].canonical_id == "generic-agent-1"
    assert len(attempt_nodes) == 2
    assert len(outcome_nodes) == 2
    assert len(failure_nodes) == 1
    assert len(recovery_nodes) == 1

    task_node = task_nodes[0]
    edges_from_task = repo.get_edges_from(task_node.node_id)
    edge_types_from_task = {e.edge_type for e in edges_from_task}
    assert IntelligenceEdgeType.TASK_EXECUTED_BY_AGENT in edge_types_from_task
    task_has_attempt_edges = [
        e for e in edges_from_task if e.edge_type is IntelligenceEdgeType.TASK_HAS_ATTEMPT
    ]
    assert len(task_has_attempt_edges) == 2

    wf_node = workflow_nodes[0]
    wf_edges = repo.get_edges_from(wf_node.node_id)
    assert any(e.edge_type is IntelligenceEdgeType.WORKFLOW_CONTAINS_TASK for e in wf_edges)

    failed_attempt = next(a for a in attempt_nodes if a.status == "failed")
    failed_edges = repo.get_edges_from(failed_attempt.node_id)
    assert any(e.edge_type is IntelligenceEdgeType.ATTEMPT_FAILED_WITH for e in failed_edges)
    assert any(e.edge_type is IntelligenceEdgeType.ATTEMPT_RECOVERED_BY for e in failed_edges)
    assert any(e.edge_type is IntelligenceEdgeType.ATTEMPT_PRODUCED_OUTCOME for e in failed_edges)


def test_graph_replay_is_idempotent_no_duplicates() -> None:
    session_factory = _make_session_factory()
    workflow_id = _build_workflow_with_retry_then_success(session_factory)

    repo = InMemoryIntelligenceGraphRepository()
    builder = EngineeringIntelligenceGraphBuilder(repo, session_factory)

    first = builder.ingest_workflow(workflow_id)
    assert first.nodes_created > 0
    assert first.edges_created > 0

    node_count_after_first = len(repo.get_nodes_by_type(IntelligenceNodeType.ATTEMPT)) + len(
        repo.get_nodes_by_type(IntelligenceNodeType.TASK)
    )

    second = builder.ingest_workflow(workflow_id)
    assert second.found is True
    assert second.nodes_created == 0
    assert second.edges_created == 0

    node_count_after_second = len(repo.get_nodes_by_type(IntelligenceNodeType.ATTEMPT)) + len(
        repo.get_nodes_by_type(IntelligenceNodeType.TASK)
    )
    assert node_count_after_second == node_count_after_first

    third = builder.ingest_workflow(workflow_id)
    assert third.nodes_created == 0
    assert third.edges_created == 0


def test_ingest_unknown_workflow_reports_not_found_without_raising() -> None:
    session_factory = _make_session_factory()
    repo = InMemoryIntelligenceGraphRepository()
    builder = EngineeringIntelligenceGraphBuilder(repo, session_factory)

    summary = builder.ingest_workflow("does-not-exist")
    assert summary.found is False
    assert summary.nodes_created == 0


def test_duplicate_canonical_edge_cannot_be_inserted_twice_in_repository() -> None:
    """Direct repository-level guarantee: even if a caller (mistakenly)
    tries to upsert the same canonical edge twice, the second call is a
    no-op, never a duplicate row."""
    from app.contracts.intelligence import IntelligenceEdge

    repo = InMemoryIntelligenceGraphRepository()
    edge = IntelligenceEdge(
        edge_id="edge:WORKFLOW_CONTAINS_TASK:node:workflow:wf1->node:task:t1",
        edge_type=IntelligenceEdgeType.WORKFLOW_CONTAINS_TASK,
        source_node_id="node:workflow:wf1",
        target_node_id="node:task:t1",
    )
    assert repo.upsert_edge(edge) is True
    assert repo.upsert_edge(edge) is False
    assert len(repo.get_edges_from("node:workflow:wf1")) == 1
