"""Tests for `WorkflowEngine.resume_workflow`: recovery after process interruption."""

import pytest
from sqlalchemy.orm import Session

from app.audit import service as audit_service
from app.audit.verification import verify_chain
from app.engine.exceptions import (
    InvalidWorkflowStateError,
    WorkflowNotFoundError,
    WorkflowResumeConflictError,
)
from app.engine.registry import ExecutorRegistry
from app.engine.workflow_engine import WorkflowEngine
from app.models.enums import AttemptStatus, StepStatus, WorkflowStatus
from app.resilience.circuit_breaker import CircuitBreakerRegistry
from app.resilience.retry import RetryPolicy
from app.services import workflow_service
from tests.support.executors import FailingExecutor, RecordingExecutor
from tests.support.fakes import FakeSleeper
from tests.support.workflow_builders import build_workflow_in_status


def _engine(db_session: Session, registry: ExecutorRegistry) -> WorkflowEngine:
    return WorkflowEngine(
        db_session,
        registry,
        circuit_breakers=CircuitBreakerRegistry(failure_threshold=3, recovery_timeout_seconds=30.0),
        retry_policy=RetryPolicy(base_delay_seconds=0.01, max_delay_seconds=0.05, jitter_ratio=0.0),
        sleeper=FakeSleeper(),
    )


def test_resume_skips_already_succeeded_steps_and_seeds_their_output(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.RUNNING,
        steps=[
            {
                "name": "already-done",
                "position": 0,
                "agent_type": "mock",
                "status": StepStatus.SUCCEEDED,
                "output_payload": {"result": "from-before-the-crash"},
            },
            {
                "name": "still-pending",
                "position": 1,
                "agent_type": "mock",
                "status": StepStatus.PENDING,
            },
        ],
    )
    executor = RecordingExecutor(output={"result": "resumed"})
    executor_registry.register("mock", executor)
    engine = _engine(db_session, executor_registry)

    result = engine.resume_workflow(workflow.id)

    assert WorkflowStatus(result.status) is WorkflowStatus.SUCCEEDED
    # Only the pending step was actually re-executed.
    assert len(executor.calls) == 1
    assert executor.calls[0].step_name == "still-pending"
    assert result.output_payload is not None
    step_outputs = {entry["name"]: entry["output"] for entry in result.output_payload["steps"]}
    assert step_outputs["already-done"] == {"result": "from-before-the-crash"}
    assert step_outputs["still-pending"] == {"result": "resumed"}


def test_resume_marks_the_interrupted_attempt_failed_and_retries_the_step(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.RUNNING,
        steps=[
            {"name": "in-flight", "position": 0, "agent_type": "mock", "status": StepStatus.RUNNING}
        ],
    )
    step = workflow.steps[0]
    dangling_attempt = workflow_service.create_step_attempt(db_session, step.id)
    assert AttemptStatus(dangling_attempt.status) is AttemptStatus.RUNNING

    executor = RecordingExecutor(output={"ok": True})
    executor_registry.register("mock", executor)
    engine = _engine(db_session, executor_registry)

    result = engine.resume_workflow(workflow.id)

    assert WorkflowStatus(result.status) is WorkflowStatus.SUCCEEDED
    db_session.refresh(dangling_attempt)
    assert AttemptStatus(dangling_attempt.status) is AttemptStatus.FAILED
    assert dangling_attempt.error_type == "EXECUTION_INTERRUPTED"
    # A fresh attempt was created and succeeded for the same step.
    resumed_step = result.steps[0]
    assert len(resumed_step.attempts) == 2
    assert AttemptStatus(resumed_step.attempts[-1].status) is AttemptStatus.SUCCEEDED


def test_resume_records_a_workflow_resumed_audit_event(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.RUNNING,
        steps=[{"name": "a", "position": 0, "agent_type": "mock", "status": StepStatus.PENDING}],
    )
    executor_registry.register("mock", RecordingExecutor(output={}))
    engine = _engine(db_session, executor_registry)

    engine.resume_workflow(workflow.id)

    events = audit_service.list_events(db_session, workflow.id)
    event_types = [event.event_type for event in events]
    assert "workflow_resumed" in event_types


def test_resume_preserves_audit_chain_integrity(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.RUNNING,
        steps=[
            {"name": "in-flight", "position": 0, "agent_type": "mock", "status": StepStatus.RUNNING}
        ],
    )
    workflow_service.create_step_attempt(db_session, workflow.steps[0].id)
    executor_registry.register("mock", RecordingExecutor(output={"ok": True}))
    engine = _engine(db_session, executor_registry)

    engine.resume_workflow(workflow.id)

    result = verify_chain(db_session, workflow.id)
    assert result.valid is True


def test_resume_a_missing_workflow_raises_not_found(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    engine = _engine(db_session, executor_registry)
    with pytest.raises(WorkflowNotFoundError):
        engine.resume_workflow("does-not-exist")


def test_resume_a_pending_workflow_is_rejected(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.PENDING,
        steps=[{"name": "a", "position": 0, "agent_type": "mock"}],
    )
    engine = _engine(db_session, executor_registry)
    with pytest.raises(InvalidWorkflowStateError):
        engine.resume_workflow(workflow.id)


def test_resume_a_succeeded_workflow_is_rejected(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.SUCCEEDED,
        steps=[
            {
                "name": "a",
                "position": 0,
                "agent_type": "mock",
                "status": StepStatus.SUCCEEDED,
                "output_payload": {},
            }
        ],
    )
    engine = _engine(db_session, executor_registry)
    with pytest.raises(InvalidWorkflowStateError):
        engine.resume_workflow(workflow.id)


def test_resume_that_fails_again_still_fails_the_workflow(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.RUNNING,
        steps=[{"name": "a", "position": 0, "agent_type": "mock", "status": StepStatus.PENDING}],
    )
    executor_registry.register("mock", FailingExecutor())
    engine = _engine(db_session, executor_registry)

    result = engine.resume_workflow(workflow.id)

    assert WorkflowStatus(result.status) is WorkflowStatus.FAILED


def test_claim_for_resume_is_atomic_and_rejects_a_stale_version(db_session: Session) -> None:
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.RUNNING,
        steps=[{"name": "a", "position": 0, "agent_type": "mock"}],
    )
    won = workflow_service.claim_workflow_for_resume(db_session, workflow.id, expected_version=1)
    assert won is True

    # A second claim using the same (now stale) version must not also win.
    lost = workflow_service.claim_workflow_for_resume(db_session, workflow.id, expected_version=1)
    assert lost is False


def test_resume_raises_conflict_error_when_the_claim_is_lost(
    db_session: Session, executor_registry: ExecutorRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.RUNNING,
        steps=[{"name": "a", "position": 0, "agent_type": "mock", "status": StepStatus.PENDING}],
    )
    monkeypatch.setattr(workflow_service, "claim_workflow_for_resume", lambda *a, **k: False)
    engine = _engine(db_session, executor_registry)

    with pytest.raises(WorkflowResumeConflictError):
        engine.resume_workflow(workflow.id)


def test_resume_with_no_remaining_steps_still_succeeds(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.RUNNING,
        steps=[
            {
                "name": "a",
                "position": 0,
                "agent_type": "mock",
                "status": StepStatus.SUCCEEDED,
                "output_payload": {"done": True},
            }
        ],
    )
    engine = _engine(db_session, executor_registry)

    result = engine.resume_workflow(workflow.id)

    assert WorkflowStatus(result.status) is WorkflowStatus.SUCCEEDED
