"""Tests for successful sequential workflow execution."""

from sqlalchemy.orm import Session

from app.engine.registry import ExecutorRegistry
from app.engine.workflow_engine import WorkflowEngine
from app.models.enums import AttemptStatus, StepStatus, WorkflowStatus
from app.models.workflow import Workflow
from app.schemas.workflow import WorkflowCreate, WorkflowStepCreate
from app.services import workflow_service
from tests.support.executors import RecordingExecutor


def _create_workflow(db_session: Session, steps: list[WorkflowStepCreate]) -> Workflow:
    data = WorkflowCreate(name="demo", input_payload={"goal": "demo"}, steps=steps)
    return workflow_service.create_workflow(db_session, data)


def test_zero_step_workflow_succeeds_with_empty_result(
    db_session: Session, workflow_engine: WorkflowEngine
) -> None:
    workflow = _create_workflow(db_session, steps=[])

    result = workflow_engine.execute_workflow(workflow.id)

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output_payload == {"steps": []}


def test_one_step_workflow_succeeds(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("mock", RecordingExecutor(output={"result": "ok"}))
    workflow = _create_workflow(
        db_session, steps=[WorkflowStepCreate(name="step-1", position=0, agent_type="mock")]
    )

    result = workflow_engine.execute_workflow(workflow.id)

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.steps[0].status == StepStatus.SUCCEEDED
    assert result.steps[0].output_payload == {"result": "ok"}


def test_multiple_steps_execute_in_position_order(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor = RecordingExecutor(output={"ok": True})
    executor_registry.register("mock", executor)
    workflow = _create_workflow(
        db_session,
        steps=[
            WorkflowStepCreate(name="second", position=1, agent_type="mock"),
            WorkflowStepCreate(name="first", position=0, agent_type="mock"),
        ],
    )

    workflow_engine.execute_workflow(workflow.id)

    assert [call.step_name for call in executor.calls] == ["first", "second"]


def test_each_executor_is_called_exactly_once(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor = RecordingExecutor(output={"ok": True})
    executor_registry.register("mock", executor)
    workflow = _create_workflow(
        db_session,
        steps=[
            WorkflowStepCreate(name="a", position=0, agent_type="mock"),
            WorkflowStepCreate(name="b", position=1, agent_type="mock"),
        ],
    )

    workflow_engine.execute_workflow(workflow.id)

    assert len(executor.calls) == 2


def test_each_successful_step_creates_one_successful_attempt(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("mock", RecordingExecutor(output={"ok": True}))
    workflow = _create_workflow(
        db_session, steps=[WorkflowStepCreate(name="step-1", position=0, agent_type="mock")]
    )

    result = workflow_engine.execute_workflow(workflow.id)

    attempts = result.steps[0].attempts
    assert len(attempts) == 1
    assert attempts[0].status == AttemptStatus.SUCCEEDED


def test_attempt_numbers_and_counts_are_consistent(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("mock", RecordingExecutor(output={"ok": True}))
    workflow = _create_workflow(
        db_session, steps=[WorkflowStepCreate(name="step-1", position=0, agent_type="mock")]
    )

    result = workflow_engine.execute_workflow(workflow.id)

    step = result.steps[0]
    assert step.attempt_count == 1
    assert step.attempts[0].attempt_number == 1


def test_previous_successful_outputs_are_passed_to_later_steps(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor = RecordingExecutor(output={"ok": True})
    executor_registry.register("mock", executor)
    workflow = _create_workflow(
        db_session,
        steps=[
            WorkflowStepCreate(name="first", position=0, agent_type="mock"),
            WorkflowStepCreate(name="second", position=1, agent_type="mock"),
        ],
    )

    workflow_engine.execute_workflow(workflow.id)

    first_call, second_call = executor.calls
    assert first_call.previous_step_outputs == {}
    assert list(second_call.previous_step_outputs.values()) == [{"ok": True}]


def test_step_output_payloads_are_persisted(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("mock", RecordingExecutor(output={"answer": 42}))
    workflow = _create_workflow(
        db_session, steps=[WorkflowStepCreate(name="step-1", position=0, agent_type="mock")]
    )

    workflow_engine.execute_workflow(workflow.id)

    reloaded = workflow_service.get_workflow(db_session, workflow.id)
    assert reloaded is not None
    assert reloaded.steps[0].output_payload == {"answer": 42}


def test_workflow_aggregated_output_is_persisted(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("mock", RecordingExecutor(output={"answer": 42}))
    workflow = _create_workflow(
        db_session, steps=[WorkflowStepCreate(name="step-1", position=0, agent_type="mock")]
    )

    result = workflow_engine.execute_workflow(workflow.id)

    assert result.output_payload is not None
    assert result.output_payload["steps"][0]["step_id"] == result.steps[0].id
    assert result.output_payload["steps"][0]["output"] == {"answer": 42}


def test_workflow_and_step_timestamps_are_updated(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("mock", RecordingExecutor(output={"ok": True}))
    workflow = _create_workflow(
        db_session, steps=[WorkflowStepCreate(name="step-1", position=0, agent_type="mock")]
    )

    result = workflow_engine.execute_workflow(workflow.id)

    assert result.started_at is not None
    assert result.completed_at is not None
    assert result.steps[0].started_at is not None
    assert result.steps[0].completed_at is not None


def test_workflow_version_changes_only_through_valid_transitions(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("mock", RecordingExecutor(output={"ok": True}))
    workflow = _create_workflow(
        db_session, steps=[WorkflowStepCreate(name="step-1", position=0, agent_type="mock")]
    )
    assert workflow.version == 1

    result = workflow_engine.execute_workflow(workflow.id)

    # PENDING -> RUNNING -> SUCCEEDED: two valid transitions since creation.
    assert result.version == 3
