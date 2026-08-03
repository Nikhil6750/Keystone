"""Tests for transaction-boundary behavior during workflow execution."""

from sqlalchemy.orm import Session

from app.engine.registry import ExecutorRegistry
from app.engine.workflow_engine import WorkflowEngine
from app.models.enums import StepStatus
from app.models.workflow import Workflow
from app.schemas.workflow import WorkflowCreate, WorkflowStepCreate
from app.services import workflow_service
from tests.support.executors import FailingExecutor, RecordingExecutor


def _create_workflow(db_session: Session, steps: list[WorkflowStepCreate]) -> Workflow:
    data = WorkflowCreate(name="demo", input_payload={}, steps=steps)
    return workflow_service.create_workflow(db_session, data)


def test_completed_earlier_steps_remain_persisted_when_a_later_step_fails(
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

    workflow_engine.execute_workflow(workflow.id)

    reloaded = workflow_service.get_workflow(db_session, workflow.id)
    assert reloaded is not None
    assert reloaded.steps[0].status == StepStatus.SUCCEEDED
    assert reloaded.steps[0].output_payload == {"ok": True}


def test_no_partial_attempt_remains_before_attempt_persistence_on_failure(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("mock", FailingExecutor())
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="step-1", position=0, agent_type="mock")]
    )

    workflow_engine.execute_workflow(workflow.id)

    reloaded = workflow_service.get_workflow(db_session, workflow.id)
    assert reloaded is not None
    assert len(reloaded.steps[0].attempts) == 1


def test_database_session_remains_usable_after_handled_failure(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("mock", FailingExecutor())
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="step-1", position=0, agent_type="mock")]
    )

    workflow_engine.execute_workflow(workflow.id)

    # The session must still be usable for further queries after a handled failure.
    all_workflows = workflow_service.list_workflows(db_session)
    assert len(all_workflows) == 1
