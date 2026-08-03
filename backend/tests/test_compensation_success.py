"""Tests for successful reverse-order compensation of a failed workflow."""

from sqlalchemy.orm import Session

from app.engine.compensation import CompensationService
from app.engine.compensation_registry import CompensationRegistry
from app.engine.demo_compensation import DEMO_COMPENSATION_HANDLER_NAME, DemoCompensationHandler
from app.models.enums import CompensationAttemptStatus, StepStatus, WorkflowStatus
from tests.support.compensation_handlers import RecordingCompensationHandler
from tests.support.workflow_builders import build_workflow_in_status


def _failed_workflow_with_one_eligible_step(db_session: Session, **overrides: object):
    steps = overrides.pop(
        "steps",
        [
            {
                "name": "s0",
                "position": 0,
                "status": StepStatus.SUCCEEDED,
                "compensation_handler": "demo.undo",
                "output_payload": {"result": "ok"},
            },
        ],
    )
    return build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.FAILED,
        error_message=overrides.pop("error_message", "original failure"),
        steps=steps,  # type: ignore[arg-type]
    )


def test_failed_workflow_transitions_to_compensating_then_compensated(
    db_session: Session,
    compensation_service: CompensationService,
    compensation_registry: CompensationRegistry,
) -> None:
    compensation_registry.register("demo.undo", RecordingCompensationHandler(output={"ok": True}))
    workflow = _failed_workflow_with_one_eligible_step(db_session)

    result = compensation_service.compensate_workflow(workflow.id)

    assert result.status == WorkflowStatus.COMPENSATED


def test_eligible_successful_steps_transition_to_compensated(
    db_session: Session,
    compensation_service: CompensationService,
    compensation_registry: CompensationRegistry,
) -> None:
    compensation_registry.register("demo.undo", RecordingCompensationHandler(output={"ok": True}))
    workflow = _failed_workflow_with_one_eligible_step(db_session)

    result = compensation_service.compensate_workflow(workflow.id)

    assert result.steps[0].status == StepStatus.COMPENSATED


def test_one_compensation_attempt_created_per_compensated_step(
    db_session: Session,
    compensation_service: CompensationService,
    compensation_registry: CompensationRegistry,
) -> None:
    compensation_registry.register("demo.undo", RecordingCompensationHandler(output={"ok": True}))
    workflow = _failed_workflow_with_one_eligible_step(db_session)

    result = compensation_service.compensate_workflow(workflow.id)

    assert len(result.steps[0].compensation_attempts) == 1


def test_successful_handler_marks_attempt_succeeded(
    db_session: Session,
    compensation_service: CompensationService,
    compensation_registry: CompensationRegistry,
) -> None:
    compensation_registry.register("demo.undo", RecordingCompensationHandler(output={"ok": True}))
    workflow = _failed_workflow_with_one_eligible_step(db_session)

    result = compensation_service.compensate_workflow(workflow.id)

    attempt = result.steps[0].compensation_attempts[0]
    assert attempt.status == CompensationAttemptStatus.SUCCEEDED
    assert attempt.output_payload == {"ok": True}


def test_workflow_becomes_compensated(
    db_session: Session,
    compensation_service: CompensationService,
    compensation_registry: CompensationRegistry,
) -> None:
    compensation_registry.register("demo.undo", RecordingCompensationHandler(output={"ok": True}))
    workflow = _failed_workflow_with_one_eligible_step(db_session)

    result = compensation_service.compensate_workflow(workflow.id)

    assert result.status == WorkflowStatus.COMPENSATED


def test_compensation_summary_is_persisted(
    db_session: Session,
    compensation_service: CompensationService,
    compensation_registry: CompensationRegistry,
) -> None:
    compensation_registry.register("demo.undo", RecordingCompensationHandler(output={"ok": True}))
    workflow = _failed_workflow_with_one_eligible_step(db_session)

    result = compensation_service.compensate_workflow(workflow.id)

    assert result.compensation_summary is not None
    assert result.compensation_summary["compensated_steps"][0]["step_id"] == result.steps[0].id
    assert result.compensation_summary["compensated_steps"][0]["handler"] == "demo.undo"


def test_original_execution_output_is_preserved(
    db_session: Session,
    compensation_service: CompensationService,
    compensation_registry: CompensationRegistry,
) -> None:
    compensation_registry.register("demo.undo", RecordingCompensationHandler(output={"ok": True}))
    workflow = _failed_workflow_with_one_eligible_step(db_session)
    original_output = workflow.steps[0].output_payload

    result = compensation_service.compensate_workflow(workflow.id)

    assert result.steps[0].output_payload == original_output


def test_original_execution_failure_context_is_preserved(
    db_session: Session,
    compensation_service: CompensationService,
    compensation_registry: CompensationRegistry,
) -> None:
    compensation_registry.register("demo.undo", RecordingCompensationHandler(output={"ok": True}))
    workflow = _failed_workflow_with_one_eligible_step(
        db_session, error_message="the original reason"
    )

    result = compensation_service.compensate_workflow(workflow.id)

    assert result.error_message == "the original reason"


def test_demo_compensation_output_is_clearly_labeled(
    db_session: Session,
    compensation_service: CompensationService,
    compensation_registry: CompensationRegistry,
) -> None:
    compensation_registry.register(DEMO_COMPENSATION_HANDLER_NAME, DemoCompensationHandler())
    workflow = _failed_workflow_with_one_eligible_step(
        db_session,
        steps=[
            {
                "name": "s0",
                "position": 0,
                "status": StepStatus.SUCCEEDED,
                "compensation_handler": DEMO_COMPENSATION_HANDLER_NAME,
            }
        ],
    )

    result = compensation_service.compensate_workflow(workflow.id)

    output = result.steps[0].compensation_attempts[0].output_payload
    assert output is not None
    assert "[DEMO]" in output["content"]
    assert output["metadata"]["execution_mode"] == "demo"
    assert output["metadata"]["compensation"] is True


def test_handlers_receive_expected_typed_context(
    db_session: Session,
    compensation_service: CompensationService,
    compensation_registry: CompensationRegistry,
) -> None:
    handler = RecordingCompensationHandler(output={"ok": True})
    compensation_registry.register("demo.undo", handler)
    workflow = _failed_workflow_with_one_eligible_step(db_session, error_message="the reason")

    compensation_service.compensate_workflow(workflow.id)

    request = handler.calls[0]
    assert request.workflow_id == workflow.id
    assert request.step_name == "s0"
    assert request.step_position == 0
    assert request.compensation_handler == "demo.undo"
    assert request.step_output == {"result": "ok"}
    assert request.original_failure == "the reason"
