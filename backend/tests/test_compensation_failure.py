"""Tests for compensation failure handling."""

import pytest
from sqlalchemy.orm import Session

from app.engine.compensation import CompensationService
from app.engine.compensation_exceptions import CompensationHandlerNotRegisteredError
from app.engine.compensation_registry import CompensationRegistry
from app.models.enums import CompensationAttemptStatus, StepStatus, WorkflowStatus
from app.services import workflow_service
from tests.support.compensation_handlers import (
    CrashingCompensationHandler,
    FailingCompensationHandler,
    RecordingCompensationHandler,
)
from tests.support.workflow_builders import build_workflow_in_status


def _failed_workflow_two_eligible_steps(db_session: Session):
    return build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.FAILED,
        error_message="original failure",
        steps=[
            {
                "name": "first",
                "position": 0,
                "status": StepStatus.SUCCEEDED,
                "compensation_handler": "good.undo",
            },
            {
                "name": "second",
                "position": 1,
                "status": StepStatus.SUCCEEDED,
                "compensation_handler": "bad.undo",
            },
        ],
    )


def test_missing_handler_fails_compensation_safely(
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
                "compensation_handler": "unregistered.undo",
            }
        ],
    )

    with pytest.raises(CompensationHandlerNotRegisteredError):
        compensation_service.compensate_workflow(workflow.id)

    reloaded = workflow_service.get_workflow(db_session, workflow.id)
    assert reloaded is not None
    assert reloaded.status == WorkflowStatus.FAILED


def test_missing_handler_creates_failed_compensation_attempt(
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
                "compensation_handler": "unregistered.undo",
            }
        ],
    )

    with pytest.raises(CompensationHandlerNotRegisteredError):
        compensation_service.compensate_workflow(workflow.id)

    reloaded = workflow_service.get_workflow(db_session, workflow.id)
    assert reloaded is not None
    attempt = reloaded.steps[0].compensation_attempts[0]
    assert attempt.status == CompensationAttemptStatus.FAILED
    assert attempt.error_type == "COMPENSATION_HANDLER_NOT_REGISTERED"


def test_handler_exception_marks_attempt_failed(
    db_session: Session,
    compensation_service: CompensationService,
    compensation_registry: CompensationRegistry,
) -> None:
    compensation_registry.register("bad.undo", FailingCompensationHandler())
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.FAILED,
        error_message="boom",
        steps=[
            {
                "name": "s0",
                "position": 0,
                "status": StepStatus.SUCCEEDED,
                "compensation_handler": "bad.undo",
            }
        ],
    )

    result = compensation_service.compensate_workflow(workflow.id)

    attempt = result.steps[0].compensation_attempts[0]
    assert attempt.status == CompensationAttemptStatus.FAILED


def test_current_compensating_step_becomes_failed(
    db_session: Session,
    compensation_service: CompensationService,
    compensation_registry: CompensationRegistry,
) -> None:
    compensation_registry.register("bad.undo", FailingCompensationHandler())
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.FAILED,
        error_message="boom",
        steps=[
            {
                "name": "s0",
                "position": 0,
                "status": StepStatus.SUCCEEDED,
                "compensation_handler": "bad.undo",
            }
        ],
    )

    result = compensation_service.compensate_workflow(workflow.id)

    assert result.steps[0].status == StepStatus.FAILED


def test_workflow_returns_to_failed(
    db_session: Session,
    compensation_service: CompensationService,
    compensation_registry: CompensationRegistry,
) -> None:
    compensation_registry.register("bad.undo", FailingCompensationHandler())
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.FAILED,
        error_message="boom",
        steps=[
            {
                "name": "s0",
                "position": 0,
                "status": StepStatus.SUCCEEDED,
                "compensation_handler": "bad.undo",
            }
        ],
    )

    result = compensation_service.compensate_workflow(workflow.id)

    assert result.status == WorkflowStatus.FAILED


def test_earlier_successful_compensations_remain_persisted(
    db_session: Session,
    compensation_service: CompensationService,
    compensation_registry: CompensationRegistry,
) -> None:
    """Reverse order means the higher-position step is compensated first. When
    that succeeds and a *later-processed* (lower-position) step then fails,
    the already-succeeded compensation must remain persisted rather than
    being rolled back."""
    compensation_registry.register("good.undo", RecordingCompensationHandler(output={"ok": True}))
    compensation_registry.register("bad.undo", FailingCompensationHandler())
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.FAILED,
        error_message="original failure",
        steps=[
            {
                "name": "first",
                "position": 0,
                "status": StepStatus.SUCCEEDED,
                "compensation_handler": "bad.undo",
            },
            {
                "name": "second",
                "position": 1,
                "status": StepStatus.SUCCEEDED,
                "compensation_handler": "good.undo",
            },
        ],
    )

    result = compensation_service.compensate_workflow(workflow.id)

    second_step = next(s for s in result.steps if s.name == "second")
    assert second_step.status == StepStatus.COMPENSATED
    assert second_step.compensation_attempts[0].status == CompensationAttemptStatus.SUCCEEDED


def test_earlier_reverse_order_steps_are_not_executed_after_failure(
    db_session: Session,
    compensation_service: CompensationService,
    compensation_registry: CompensationRegistry,
) -> None:
    good_handler = RecordingCompensationHandler(output={"ok": True})
    compensation_registry.register("good.undo", good_handler)
    compensation_registry.register("bad.undo", FailingCompensationHandler())
    workflow = _failed_workflow_two_eligible_steps(db_session)

    # "second" (position 1) is compensated first (reverse order) and fails;
    # "first" (position 0) must never be reached.
    compensation_service.compensate_workflow(workflow.id)

    assert len(good_handler.calls) == 0


def test_workflow_never_reports_compensated_on_failure(
    db_session: Session,
    compensation_service: CompensationService,
    compensation_registry: CompensationRegistry,
) -> None:
    compensation_registry.register("bad.undo", FailingCompensationHandler())
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.FAILED,
        error_message="boom",
        steps=[
            {
                "name": "s0",
                "position": 0,
                "status": StepStatus.SUCCEEDED,
                "compensation_handler": "bad.undo",
            }
        ],
    )

    result = compensation_service.compensate_workflow(workflow.id)

    assert result.status != WorkflowStatus.COMPENSATED


def test_safe_error_details_are_persisted(
    db_session: Session,
    compensation_service: CompensationService,
    compensation_registry: CompensationRegistry,
) -> None:
    compensation_registry.register(
        "bad.undo", FailingCompensationHandler(error_message="handler-specific failure")
    )
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.FAILED,
        error_message="boom",
        steps=[
            {
                "name": "s0",
                "position": 0,
                "status": StepStatus.SUCCEEDED,
                "compensation_handler": "bad.undo",
            }
        ],
    )

    result = compensation_service.compensate_workflow(workflow.id)

    attempt = result.steps[0].compensation_attempts[0]
    assert attempt.error_message == "handler-specific failure"
    assert attempt.error_type == "COMPENSATION_EXECUTION_FAILED"


def test_raw_exceptions_and_stack_traces_are_not_exposed(
    db_session: Session,
    compensation_service: CompensationService,
    compensation_registry: CompensationRegistry,
) -> None:
    compensation_registry.register("bad.undo", CrashingCompensationHandler())
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.FAILED,
        error_message="boom",
        steps=[
            {
                "name": "s0",
                "position": 0,
                "status": StepStatus.SUCCEEDED,
                "compensation_handler": "bad.undo",
            }
        ],
    )

    # An unexpected (non-CompensationError) handler exception is still a
    # normal handled compensation failure: it returns the persisted failed
    # workflow rather than raising, exactly like a handled step-execution
    # failure does in Phase 2/3.
    result = compensation_service.compensate_workflow(workflow.id)

    assert result.status == WorkflowStatus.FAILED
    attempt = result.steps[0].compensation_attempts[0]
    assert attempt.error_message is not None
    assert "Traceback" not in attempt.error_message
    assert "RuntimeError" not in attempt.error_message
