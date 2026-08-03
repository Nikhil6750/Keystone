"""Tests for which steps are eligible for compensation, and in what order."""

from sqlalchemy.orm import Session

from app.engine.compensation import CompensationService
from app.engine.compensation_registry import CompensationRegistry
from app.models.enums import StepStatus, WorkflowStatus
from tests.support.compensation_handlers import RecordingCompensationHandler
from tests.support.workflow_builders import build_workflow_in_status


def test_eligible_steps_compensated_in_descending_position_order(
    db_session: Session,
    compensation_service: CompensationService,
    compensation_registry: CompensationRegistry,
) -> None:
    handler = RecordingCompensationHandler(output={"ok": True})
    compensation_registry.register("demo.undo", handler)
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.FAILED,
        error_message="boom",
        steps=[
            {
                "name": "s0",
                "position": 0,
                "status": StepStatus.SUCCEEDED,
                "compensation_handler": "demo.undo",
            },
            {
                "name": "s1",
                "position": 1,
                "status": StepStatus.SUCCEEDED,
                "compensation_handler": "demo.undo",
            },
            {"name": "s2", "position": 2, "status": StepStatus.FAILED},
        ],
    )

    compensation_service.compensate_workflow(workflow.id)

    positions_called = [call.step_position for call in handler.calls]
    assert positions_called == [1, 0]


def test_steps_without_handlers_are_not_executed(
    db_session: Session,
    compensation_service: CompensationService,
    compensation_registry: CompensationRegistry,
) -> None:
    handler = RecordingCompensationHandler(output={"ok": True})
    compensation_registry.register("demo.undo", handler)
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.FAILED,
        error_message="boom",
        steps=[
            {
                "name": "s0",
                "position": 0,
                "status": StepStatus.SUCCEEDED,
                "compensation_handler": None,
            },
            {"name": "s1", "position": 1, "status": StepStatus.FAILED},
        ],
    )

    compensation_service.compensate_workflow(workflow.id)

    assert len(handler.calls) == 0


def test_steps_without_handlers_appear_as_not_configured(
    db_session: Session, compensation_service: CompensationService
) -> None:
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.FAILED,
        error_message="boom",
        steps=[
            {
                "name": "s0",
                "position": 0,
                "status": StepStatus.SUCCEEDED,
                "compensation_handler": None,
            },
            {"name": "s1", "position": 1, "status": StepStatus.FAILED},
        ],
    )

    result = compensation_service.compensate_workflow(workflow.id)

    summary = result.compensation_summary
    assert summary is not None
    assert len(summary["not_configured_steps"]) == 1
    assert summary["not_configured_steps"][0]["name"] == "s0"


def test_failed_pending_skipped_cancelled_steps_are_ignored(
    db_session: Session,
    compensation_service: CompensationService,
    compensation_registry: CompensationRegistry,
) -> None:
    handler = RecordingCompensationHandler(output={"ok": True})
    compensation_registry.register("demo.undo", handler)
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.FAILED,
        error_message="boom",
        steps=[
            {
                "name": "pending",
                "position": 0,
                "status": StepStatus.PENDING,
                "compensation_handler": "demo.undo",
            },
            {
                "name": "skipped",
                "position": 1,
                "status": StepStatus.SKIPPED,
                "compensation_handler": "demo.undo",
            },
            {
                "name": "cancelled",
                "position": 2,
                "status": StepStatus.CANCELLED,
                "compensation_handler": "demo.undo",
            },
            {
                "name": "failed",
                "position": 3,
                "status": StepStatus.FAILED,
                "compensation_handler": "demo.undo",
            },
        ],
    )

    compensation_service.compensate_workflow(workflow.id)

    assert len(handler.calls) == 0


def test_failing_execution_step_is_not_compensated(
    db_session: Session,
    compensation_service: CompensationService,
    compensation_registry: CompensationRegistry,
) -> None:
    handler = RecordingCompensationHandler(output={"ok": True})
    compensation_registry.register("demo.undo", handler)
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.FAILED,
        error_message="boom",
        steps=[
            {
                "name": "good",
                "position": 0,
                "status": StepStatus.SUCCEEDED,
                "compensation_handler": "demo.undo",
            },
            {
                "name": "bad",
                "position": 1,
                "status": StepStatus.FAILED,
                "compensation_handler": "demo.undo",
            },
        ],
    )

    result = compensation_service.compensate_workflow(workflow.id)

    called_positions = [call.step_position for call in handler.calls]
    assert 1 not in called_positions
    bad_step = next(s for s in result.steps if s.name == "bad")
    assert bad_step.status == StepStatus.FAILED


def test_zero_eligible_steps_results_in_compensated_workflow_with_empty_list(
    db_session: Session, compensation_service: CompensationService
) -> None:
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.FAILED,
        error_message="boom",
        steps=[
            {"name": "s0", "position": 0, "status": StepStatus.FAILED},
        ],
    )

    result = compensation_service.compensate_workflow(workflow.id)

    assert result.status == WorkflowStatus.COMPENSATED
    assert result.compensation_summary is not None
    assert result.compensation_summary["compensated_steps"] == []
