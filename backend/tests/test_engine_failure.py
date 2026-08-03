"""Tests for workflow execution failure handling."""

import pytest
from sqlalchemy.orm import Session

from app.engine.exceptions import InvalidWorkflowStateError, WorkflowNotFoundError
from app.engine.registry import ExecutorNotRegisteredError, ExecutorRegistry
from app.engine.workflow_engine import WorkflowEngine
from app.models.enums import AttemptStatus, StepStatus, WorkflowStatus
from app.models.workflow import Workflow
from app.schemas.workflow import WorkflowCreate, WorkflowStepCreate
from app.services import workflow_service
from tests.support.executors import CrashingExecutor, FailingExecutor, RecordingExecutor


def _create_workflow(db_session: Session, steps: list[WorkflowStepCreate]) -> Workflow:
    data = WorkflowCreate(name="demo", input_payload={}, steps=steps)
    return workflow_service.create_workflow(db_session, data)


def test_missing_executor_fails_current_step_and_workflow(
    db_session: Session, workflow_engine: WorkflowEngine
) -> None:
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="step-1", position=0, agent_type="unregistered")]
    )

    with pytest.raises(ExecutorNotRegisteredError):
        workflow_engine.execute_workflow(workflow.id)

    reloaded = workflow_service.get_workflow(db_session, workflow.id)
    assert reloaded is not None
    assert reloaded.status == WorkflowStatus.FAILED
    assert reloaded.steps[0].status == StepStatus.FAILED


def test_missing_executor_failure_creates_failed_attempt(
    db_session: Session, workflow_engine: WorkflowEngine
) -> None:
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="step-1", position=0, agent_type="unregistered")]
    )

    with pytest.raises(ExecutorNotRegisteredError):
        workflow_engine.execute_workflow(workflow.id)

    reloaded = workflow_service.get_workflow(db_session, workflow.id)
    assert reloaded is not None
    attempts = reloaded.steps[0].attempts
    assert len(attempts) == 1
    assert attempts[0].status == AttemptStatus.FAILED
    assert attempts[0].error_type == "AGENT_EXECUTOR_NOT_REGISTERED"


def test_raised_expected_exception_fails_current_step(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("mock", FailingExecutor(error_message="boom", error_type="BOOM"))
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="step-1", position=0, agent_type="mock")]
    )

    result = workflow_engine.execute_workflow(workflow.id)

    assert result.status == WorkflowStatus.FAILED
    assert result.steps[0].status == StepStatus.FAILED


def test_failure_error_type_and_safe_message_are_stored(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("mock", FailingExecutor(error_message="boom", error_type="BOOM"))
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="step-1", position=0, agent_type="mock")]
    )

    result = workflow_engine.execute_workflow(workflow.id)

    attempt = result.steps[0].attempts[0]
    assert attempt.error_type == "BOOM"
    assert attempt.error_message == "boom"
    assert result.error_message == "boom"


def test_later_steps_remain_pending_after_failure(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("mock", FailingExecutor())
    workflow = _create_workflow(
        db_session,
        [
            WorkflowStepCreate(name="first", position=0, agent_type="mock"),
            WorkflowStepCreate(name="second", position=1, agent_type="mock"),
        ],
    )

    result = workflow_engine.execute_workflow(workflow.id)

    assert result.steps[1].status == StepStatus.PENDING


def test_earlier_successful_outputs_remain_persisted_after_later_failure(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("good", RecordingExecutor(output={"ok": True}))
    executor_registry.register("bad", FailingExecutor())
    workflow = _create_workflow(
        db_session,
        [
            WorkflowStepCreate(name="first", position=0, agent_type="good"),
            WorkflowStepCreate(name="second", position=1, agent_type="bad"),
        ],
    )

    result = workflow_engine.execute_workflow(workflow.id)

    assert result.steps[0].status == StepStatus.SUCCEEDED
    assert result.steps[0].output_payload == {"ok": True}


def test_failed_execution_does_not_leave_running_attempts(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("mock", FailingExecutor())
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="step-1", position=0, agent_type="mock")]
    )

    result = workflow_engine.execute_workflow(workflow.id)

    for attempt in result.steps[0].attempts:
        assert attempt.status != AttemptStatus.RUNNING


def test_reexecuting_a_failed_workflow_is_rejected(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("mock", FailingExecutor())
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="step-1", position=0, agent_type="mock")]
    )
    workflow_engine.execute_workflow(workflow.id)

    with pytest.raises(InvalidWorkflowStateError):
        workflow_engine.execute_workflow(workflow.id)


def test_executing_an_already_running_workflow_is_rejected(
    db_session: Session, workflow_engine: WorkflowEngine
) -> None:
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="step-1", position=0, agent_type="mock")]
    )
    workflow_service.transition_workflow(db_session, workflow.id, WorkflowStatus.RUNNING)

    with pytest.raises(InvalidWorkflowStateError):
        workflow_engine.execute_workflow(workflow.id)


def test_executing_a_succeeded_workflow_is_rejected(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("mock", RecordingExecutor(output={"ok": True}))
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="step-1", position=0, agent_type="mock")]
    )
    workflow_engine.execute_workflow(workflow.id)

    with pytest.raises(InvalidWorkflowStateError):
        workflow_engine.execute_workflow(workflow.id)


def test_missing_workflow_execution_raises_not_found(
    db_session: Session, workflow_engine: WorkflowEngine
) -> None:
    with pytest.raises(WorkflowNotFoundError):
        workflow_engine.execute_workflow("does-not-exist")


def test_step_failure_response_still_exposes_persisted_failed_workflow_state(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("mock", FailingExecutor(error_message="boom"))
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="step-1", position=0, agent_type="mock")]
    )

    workflow_engine.execute_workflow(workflow.id)

    reloaded = workflow_service.get_workflow(db_session, workflow.id)
    assert reloaded is not None
    assert reloaded.status == WorkflowStatus.FAILED
    assert reloaded.error_message == "boom"


def test_unexpected_exception_does_not_produce_fake_success(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("mock", CrashingExecutor())
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="step-1", position=0, agent_type="mock")]
    )

    with pytest.raises(RuntimeError):
        workflow_engine.execute_workflow(workflow.id)

    reloaded = workflow_service.get_workflow(db_session, workflow.id)
    assert reloaded is not None
    assert reloaded.status == WorkflowStatus.FAILED
    assert reloaded.steps[0].status == StepStatus.FAILED
