"""Stage 9E: SQLAlchemy graph persistence -- restart/reload, historical
failure preservation, duplicate-ingestion safety."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.contracts.intelligence import (
    FailureAttributionCategory,
    IntelligenceNodeType,
)
from app.database.base import Base
from app.engine.intelligence.builder import EngineeringIntelligenceGraphBuilder
from app.engine.intelligence.graph_repository import SqlAlchemyIntelligenceGraphRepository
from app.models.enums import AttemptStatus, StepStatus, WorkflowStatus
from app.models.intelligence import IntelligenceEdgeRecord, IntelligenceNodeRecord
from app.schemas.workflow import WorkflowCreate, WorkflowStepCreate
from app.services import workflow_service


def _shared_sqlite_session_factory() -> Callable[[], Session]:
    # A single shared in-memory connection (StaticPool) so every fresh
    # `sessionmaker()` call still sees the same schema/data -- simulates a
    # process restart without needing a real on-disk database file.
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _build_failed_then_succeeded_workflow(session_factory: Callable[[], Session]) -> str:
    with session_factory() as session:
        workflow = workflow_service.create_workflow(
            session,
            WorkflowCreate(
                name="wf-restart",
                steps=[
                    WorkflowStepCreate(
                        name="do work",
                        position=0,
                        agent_type="restart-agent",
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
            error_message="timed out",
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


def test_sqlalchemy_repository_restart_reload_reconstructs_graph() -> None:
    session_factory = _shared_sqlite_session_factory()
    workflow_id = _build_failed_then_succeeded_workflow(session_factory)

    graph_repo = SqlAlchemyIntelligenceGraphRepository(session_factory=session_factory)
    builder = EngineeringIntelligenceGraphBuilder(graph_repo, session_factory)
    summary = builder.ingest_workflow(workflow_id)
    assert summary.found is True
    assert summary.nodes_created > 0

    # Simulate a process restart: a brand new repository instance bound to
    # the same underlying database must see exactly what was persisted.
    reloaded_repo = SqlAlchemyIntelligenceGraphRepository(session_factory=session_factory)
    attempts = reloaded_repo.get_nodes_by_type(
        IntelligenceNodeType.ATTEMPT, workflow_id=workflow_id
    )
    assert len(attempts) == 2
    failures = reloaded_repo.list_failure_attributions(workflow_id=workflow_id)
    assert len(failures) == 1
    assert failures[0].category is FailureAttributionCategory.TIMEOUT


def test_historical_failure_preserved_after_later_success_on_restart() -> None:
    session_factory = _shared_sqlite_session_factory()
    workflow_id = _build_failed_then_succeeded_workflow(session_factory)

    graph_repo = SqlAlchemyIntelligenceGraphRepository(session_factory=session_factory)
    builder = EngineeringIntelligenceGraphBuilder(graph_repo, session_factory)
    builder.ingest_workflow(workflow_id)

    # The first, failed attempt's node/failure evidence must still exist
    # even though the step ultimately succeeded on its second attempt.
    attempts = graph_repo.get_nodes_by_type(IntelligenceNodeType.ATTEMPT, workflow_id=workflow_id)
    statuses = sorted(a.status for a in attempts if a.status is not None)
    assert statuses == ["failed", "succeeded"]

    failures = graph_repo.list_failure_attributions(workflow_id=workflow_id)
    assert len(failures) == 1
    failed_attempt_node = next(a for a in attempts if a.status == "failed")
    assert failures[0].attempt_node_id == failed_attempt_node.node_id


def test_duplicate_ingestion_across_restart_does_not_duplicate_rows() -> None:
    session_factory = _shared_sqlite_session_factory()
    workflow_id = _build_failed_then_succeeded_workflow(session_factory)

    graph_repo = SqlAlchemyIntelligenceGraphRepository(session_factory=session_factory)
    builder = EngineeringIntelligenceGraphBuilder(graph_repo, session_factory)
    builder.ingest_workflow(workflow_id)

    with session_factory() as session:
        node_count_after_first = session.query(IntelligenceNodeRecord).count()
        edge_count_after_first = session.query(IntelligenceEdgeRecord).count()

    # A brand new builder/repository pair (simulating a rebuild process
    # started after a restart) replaying the same workflow must not add
    # anything new.
    rebuild_repo = SqlAlchemyIntelligenceGraphRepository(session_factory=session_factory)
    rebuild_builder = EngineeringIntelligenceGraphBuilder(rebuild_repo, session_factory)
    second_summary = rebuild_builder.ingest_workflow(workflow_id)
    assert second_summary.nodes_created == 0
    assert second_summary.edges_created == 0

    with session_factory() as session:
        node_count_after_second = session.query(IntelligenceNodeRecord).count()
        edge_count_after_second = session.query(IntelligenceEdgeRecord).count()

    assert node_count_after_second == node_count_after_first
    assert edge_count_after_second == edge_count_after_first
