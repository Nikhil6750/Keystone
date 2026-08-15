"""Stage 9E: reliability signals and evidence-based failure attribution."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.contracts.intelligence import FailureAttributionCategory
from app.contracts.quality import (
    QualityEvidence,
    QualityGateResult,
    QualityGateStatus,
    QualityGateType,
    QualityRun,
    QualityVerdict,
)
from app.database.base import Base
from app.engine.intelligence.builder import EngineeringIntelligenceGraphBuilder
from app.engine.intelligence.graph_repository import InMemoryIntelligenceGraphRepository
from app.engine.intelligence.query_service import EngineeringIntelligenceQueryService
from app.engine.quality.repository import InMemoryQualityRepository
from app.models.enums import AttemptStatus, StepStatus, WorkflowStatus
from app.schemas.workflow import WorkflowCreate, WorkflowStepCreate
from app.services import workflow_service


def _make_session_factory() -> Callable[[], Session]:
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _run_step_to_completion(
    session_factory: Callable[[], Session],
    *,
    workflow_name: str,
    agent_type: str,
    task_type: str,
    outcomes: list[tuple[AttemptStatus, str | None]],
    skill_id: str | None = None,
    skill_version: str | None = None,
    max_attempts: int = 3,
) -> str:
    """Build one workflow/step and drive `outcomes` (one entry per attempt,
    `(status, error_type)`) through the real step/workflow state machine."""
    with session_factory() as session:
        payload: dict[str, object] = {"task_type": task_type}
        if skill_id:
            payload["skill_id"] = skill_id
            payload["skill_version"] = skill_version
        workflow = workflow_service.create_workflow(
            session,
            WorkflowCreate(
                name=workflow_name,
                steps=[
                    WorkflowStepCreate(
                        name="do work",
                        position=0,
                        agent_type=agent_type,
                        input_payload=payload,
                        max_attempts=max_attempts,
                    )
                ],
            ),
        )
        step = workflow.steps[0]
        workflow_service.transition_workflow(session, workflow.id, WorkflowStatus.RUNNING)
        workflow_service.transition_step(session, step.id, StepStatus.RUNNING)

        for idx, (status, error_type) in enumerate(outcomes):
            attempt = workflow_service.create_step_attempt(session, step.id)
            if status is AttemptStatus.SUCCEEDED:
                workflow_service.complete_step_attempt(
                    session, attempt.id, status=status, output_payload={"ok": True}
                )
            else:
                workflow_service.complete_step_attempt(
                    session,
                    attempt.id,
                    status=status,
                    error_type=error_type,
                    error_message=f"failure #{idx + 1}",
                )
            is_last = idx == len(outcomes) - 1
            if status is AttemptStatus.SUCCEEDED:
                workflow_service.transition_step(session, step.id, StepStatus.SUCCEEDED)
            elif is_last:
                workflow_service.transition_step(session, step.id, StepStatus.FAILED)
            else:
                workflow_service.transition_step(session, step.id, StepStatus.RETRYING)
                workflow_service.transition_step(session, step.id, StepStatus.RUNNING)

        final_status = (
            WorkflowStatus.SUCCEEDED
            if outcomes[-1][0] is AttemptStatus.SUCCEEDED
            else WorkflowStatus.FAILED
        )
        workflow_service.transition_workflow(session, workflow.id, final_status)
        return workflow.id


def _quality_run(
    *,
    workflow_id: str,
    agent_id: str,
    attempt_number: int,
    gate_status: QualityGateStatus,
) -> QualityRun:
    gate = QualityGateResult(
        gate_id="python-tests",
        gate_type=QualityGateType.TEST,
        name="Tests",
        status=gate_status,
        required=True,
        evidence=QualityEvidence(summary="evidence"),
        failure_reason=None if gate_status == QualityGateStatus.PASSED else "tests failed",
    )
    verdict = QualityVerdict.compute([gate], verdict_id=f"v-{workflow_id}-{attempt_number}")
    return QualityRun(
        run_id=f"qrun-{workflow_id}-{attempt_number}",
        execution_id=f"exec-{workflow_id}",
        workflow_id=workflow_id,
        task_id="task-key",
        attempt_number=attempt_number,
        agent_id=agent_id,
        verdict=verdict,
        gate_results=(gate,),
        created_at=datetime.now(UTC),
    )


def test_task_and_agent_reliability_counts_success_and_failure() -> None:
    session_factory = _make_session_factory()
    graph_repo = InMemoryIntelligenceGraphRepository()
    builder = EngineeringIntelligenceGraphBuilder(graph_repo, session_factory)
    query = EngineeringIntelligenceQueryService(graph_repo)

    wf1 = _run_step_to_completion(
        session_factory,
        workflow_name="wf-1",
        agent_type="agent-alpha",
        task_type="code_generation",
        outcomes=[(AttemptStatus.SUCCEEDED, None)],
    )
    wf2 = _run_step_to_completion(
        session_factory,
        workflow_name="wf-2",
        agent_type="agent-alpha",
        task_type="code_generation",
        outcomes=[(AttemptStatus.FAILED, "AGENT_TIMEOUT"), (AttemptStatus.SUCCEEDED, None)],
    )
    wf3 = _run_step_to_completion(
        session_factory,
        workflow_name="wf-3",
        agent_type="agent-beta",
        task_type="code_generation",
        outcomes=[(AttemptStatus.FAILED, "AGENT_TIMEOUT")],
        max_attempts=1,
    )

    for wf in (wf1, wf2, wf3):
        builder.ingest_workflow(wf)

    task_reliability = query.get_task_reliability(task_type="code_generation")
    # attempts: wf1=1, wf2=2, wf3=1 -> 4 total
    assert task_reliability.attempt_count == 4
    assert task_reliability.success_count == 2
    assert task_reliability.failure_count == 2
    assert task_reliability.recovery_count == 1  # only wf2's 2nd attempt
    assert task_reliability.success_rate == 0.5
    assert task_reliability.sample_size_is_low is True  # 4 < LOW_SAMPLE_SIZE_THRESHOLD

    alpha_reliability = query.get_agent_reliability("agent-alpha", task_type="code_generation")
    assert alpha_reliability.observed_executions == 3
    assert alpha_reliability.successful_executions == 2
    assert alpha_reliability.failed_executions == 1
    assert alpha_reliability.recovery_count == 1

    beta_reliability = query.get_agent_reliability("agent-beta")
    assert beta_reliability.observed_executions == 1
    assert beta_reliability.successful_executions == 0
    assert beta_reliability.failed_executions == 1


def test_skill_reliability_scoped_by_skill_and_task_type() -> None:
    session_factory = _make_session_factory()
    graph_repo = InMemoryIntelligenceGraphRepository()
    builder = EngineeringIntelligenceGraphBuilder(graph_repo, session_factory)
    query = EngineeringIntelligenceQueryService(graph_repo)

    wf1 = _run_step_to_completion(
        session_factory,
        workflow_name="wf-skill-1",
        agent_type="agent-alpha",
        task_type="code_generation",
        outcomes=[(AttemptStatus.SUCCEEDED, None)],
        skill_id="skill-x",
        skill_version="1.0.0",
    )
    wf2 = _run_step_to_completion(
        session_factory,
        workflow_name="wf-skill-2",
        agent_type="agent-alpha",
        task_type="code_generation",
        outcomes=[(AttemptStatus.FAILED, "AGENT_TIMEOUT")],
        skill_id="skill-x",
        skill_version="1.0.0",
        max_attempts=1,
    )

    for wf in (wf1, wf2):
        builder.ingest_workflow(wf)

    skill_reliability = query.get_skill_reliability("skill-x", "1.0.0")
    assert skill_reliability.uses == 2
    assert skill_reliability.successful_uses == 1
    assert skill_reliability.failed_uses == 1
    assert skill_reliability.success_rate == 0.5

    unrelated = query.get_skill_reliability("skill-does-not-exist")
    assert unrelated.uses == 0
    assert unrelated.success_rate is None


def test_quality_verified_success_and_rejection_tracked_separately_from_execution() -> None:
    """A required Stage 9D gate failure on an attempt whose *execution*
    succeeded must still show up as a quality rejection -- agent success
    != quality success (see Stage 9D)."""
    session_factory = _make_session_factory()
    graph_repo = InMemoryIntelligenceGraphRepository()
    quality_repo = InMemoryQualityRepository()
    builder = EngineeringIntelligenceGraphBuilder(
        graph_repo, session_factory, quality_repository=quality_repo
    )
    query = EngineeringIntelligenceQueryService(graph_repo)

    wf_id = _run_step_to_completion(
        session_factory,
        workflow_name="wf-quality-reject",
        agent_type="agent-alpha",
        task_type="code_generation",
        outcomes=[(AttemptStatus.SUCCEEDED, None)],
    )
    quality_repo.save_run(
        _quality_run(
            workflow_id=wf_id,
            agent_id="agent-alpha",
            attempt_number=1,
            gate_status=QualityGateStatus.FAILED,
        )
    )

    summary = builder.ingest_workflow(wf_id)
    assert summary.quality_runs_linked == 1

    agent_reliability = query.get_agent_reliability("agent-alpha", task_type="code_generation")
    assert agent_reliability.successful_executions == 1  # execution succeeded
    assert agent_reliability.quality_verified_successes == 0  # but quality rejected it

    task_reliability = query.get_task_reliability(task_type="code_generation")
    assert task_reliability.quality_rejection_count == 1

    failures = query.get_failure_history(
        category=FailureAttributionCategory.QUALITY_GATE_FAILURE
    )
    assert len(failures) == 1
    assert failures[0].is_known is True
    assert "qrun-" in failures[0].evidence_ids[0]


def test_skill_related_quality_failure_attributed_as_skill_verification_failure() -> None:
    session_factory = _make_session_factory()
    graph_repo = InMemoryIntelligenceGraphRepository()
    quality_repo = InMemoryQualityRepository()
    builder = EngineeringIntelligenceGraphBuilder(
        graph_repo, session_factory, quality_repository=quality_repo
    )
    query = EngineeringIntelligenceQueryService(graph_repo)

    wf_id = _run_step_to_completion(
        session_factory,
        workflow_name="wf-skill-quality-reject",
        agent_type="agent-alpha",
        task_type="code_generation",
        outcomes=[(AttemptStatus.SUCCEEDED, None)],
        skill_id="skill-y",
        skill_version="2.0.0",
    )
    quality_repo.save_run(
        _quality_run(
            workflow_id=wf_id,
            agent_id="agent-alpha",
            attempt_number=1,
            gate_status=QualityGateStatus.FAILED,
        )
    )
    builder.ingest_workflow(wf_id)

    failures = query.get_failure_history(
        category=FailureAttributionCategory.SKILL_VERIFICATION_FAILURE
    )
    assert len(failures) == 1
    assert failures[0].skill_id == "skill-y"


def test_failure_attribution_categories_execution_timeout_and_recovery_exhaustion() -> None:
    session_factory = _make_session_factory()
    graph_repo = InMemoryIntelligenceGraphRepository()
    builder = EngineeringIntelligenceGraphBuilder(graph_repo, session_factory)
    query = EngineeringIntelligenceQueryService(graph_repo)

    # Single, non-retried timeout failure (max_attempts=1: no recovery attempted).
    wf_timeout = _run_step_to_completion(
        session_factory,
        workflow_name="wf-timeout",
        agent_type="agent-gamma",
        task_type="lint",
        outcomes=[(AttemptStatus.FAILED, "AGENT_TIMEOUT")],
        max_attempts=1,
    )
    # Two attempts, both fail -> recovery exhaustion on the final attempt.
    wf_exhausted = _run_step_to_completion(
        session_factory,
        workflow_name="wf-exhausted",
        agent_type="agent-gamma",
        task_type="lint",
        outcomes=[(AttemptStatus.FAILED, "AGENT_TIMEOUT"), (AttemptStatus.FAILED, "AGENT_TIMEOUT")],
        max_attempts=2,
    )
    # Unrecognized error_type -> unknown, not fabricated.
    wf_unknown = _run_step_to_completion(
        session_factory,
        workflow_name="wf-unknown",
        agent_type="agent-gamma",
        task_type="lint",
        outcomes=[(AttemptStatus.FAILED, "SOME_NOVEL_ERROR_TYPE_NEVER_SEEN")],
        max_attempts=1,
    )

    for wf in (wf_timeout, wf_exhausted, wf_unknown):
        builder.ingest_workflow(wf)

    all_failures = query.get_failure_history(agent_type="agent-gamma", limit=20)
    categories = {f.category for f in all_failures}
    assert FailureAttributionCategory.TIMEOUT in categories
    assert FailureAttributionCategory.RECOVERY_EXHAUSTION in categories
    assert FailureAttributionCategory.UNKNOWN in categories

    unknown_ones = [f for f in all_failures if f.category is FailureAttributionCategory.UNKNOWN]
    assert all(f.is_known is False for f in unknown_ones)

    exhaustion_ones = [
        f for f in all_failures if f.category is FailureAttributionCategory.RECOVERY_EXHAUSTION
    ]
    assert len(exhaustion_ones) == 1
    assert exhaustion_ones[0].is_known is True


def test_quality_gate_intelligence_aggregates_pass_fail_counts_and_frequent_failures() -> None:
    session_factory = _make_session_factory()
    graph_repo = InMemoryIntelligenceGraphRepository()
    quality_repo = InMemoryQualityRepository()
    builder = EngineeringIntelligenceGraphBuilder(
        graph_repo, session_factory, quality_repository=quality_repo
    )
    query = EngineeringIntelligenceQueryService(graph_repo)

    wf1 = _run_step_to_completion(
        session_factory,
        workflow_name="wf-gate-1",
        agent_type="agent-delta",
        task_type="code_generation",
        outcomes=[(AttemptStatus.SUCCEEDED, None)],
    )
    wf2 = _run_step_to_completion(
        session_factory,
        workflow_name="wf-gate-2",
        agent_type="agent-delta",
        task_type="code_generation",
        outcomes=[(AttemptStatus.SUCCEEDED, None)],
    )
    quality_repo.save_run(
        _quality_run(
            workflow_id=wf1,
            agent_id="agent-delta",
            attempt_number=1,
            gate_status=QualityGateStatus.PASSED,
        )
    )
    quality_repo.save_run(
        _quality_run(
            workflow_id=wf2,
            agent_id="agent-delta",
            attempt_number=1,
            gate_status=QualityGateStatus.FAILED,
        )
    )
    builder.ingest_workflow(wf1)
    builder.ingest_workflow(wf2)

    intelligence = query.get_quality_gate_intelligence(agent_type="agent-delta")
    assert intelligence.total_gate_results == 2
    assert intelligence.passed_count == 1
    assert intelligence.failed_count == 1
    assert intelligence.most_frequent_failed_gate_types == (("test", 1),)
