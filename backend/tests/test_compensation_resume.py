"""Tests for `CompensationService.resume_compensation`: recovery after a
process interruption mid-compensation."""

import pytest
from sqlalchemy.orm import Session

from app.audit import service as audit_service
from app.audit.verification import verify_chain
from app.engine.compensation import CompensationService
from app.engine.compensation_exceptions import (
    CompensationResumeConflictError,
    InvalidCompensationStateError,
)
from app.engine.compensation_registry import CompensationRegistry
from app.engine.exceptions import WorkflowNotFoundError
from app.models.enums import CompensationAttemptStatus, StepStatus, WorkflowStatus
from app.services import workflow_service
from tests.support.compensation_handlers import (
    FailingCompensationHandler,
    RecordingCompensationHandler,
)
from tests.support.workflow_builders import build_workflow_in_status


def test_resume_compensation_skips_already_compensated_step(
    db_session: Session,
    compensation_service: CompensationService,
    compensation_registry: CompensationRegistry,
) -> None:
    # Reverse-order: highest position ("c") would be compensated first, so a
    # realistic crash mid-compensation leaves it already COMPENSATED, the
    # next one interrupted, and the lowest position untouched.
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.COMPENSATING,
        error_message="boom",
        steps=[
            {
                "name": "a",
                "position": 0,
                "status": StepStatus.SUCCEEDED,
                "compensation_handler": "demo.undo",
                "output_payload": {},
            },
            {
                "name": "b",
                "position": 1,
                "status": StepStatus.COMPENSATING,
                "compensation_handler": "demo.undo",
                "output_payload": {},
            },
            {
                "name": "c",
                "position": 2,
                "status": StepStatus.COMPENSATED,
                "compensation_handler": "demo.undo",
                "output_payload": {},
            },
        ],
    )
    step_a, step_b, step_c = workflow.steps
    already_done = workflow_service.create_compensation_attempt(
        db_session, step_c.id, handler_name="demo.undo"
    )
    workflow_service.complete_compensation_attempt(
        db_session,
        already_done.id,
        status=CompensationAttemptStatus.SUCCEEDED,
        output_payload={"reversed": step_c.id},
    )
    workflow_service.create_compensation_attempt(db_session, step_b.id, handler_name="demo.undo")

    handler = RecordingCompensationHandler(output={"ok": True})
    compensation_registry.register("demo.undo", handler)

    result = compensation_service.resume_compensation(workflow.id)

    assert WorkflowStatus(result.status) is WorkflowStatus.COMPENSATED
    # "c" was never re-invoked; only "b" and "a" were.
    called_step_ids = [call.step_id for call in handler.calls]
    assert called_step_ids == [step_b.id, step_a.id]


def test_resume_compensation_marks_interrupted_attempt_failed_and_retries(
    db_session: Session,
    compensation_service: CompensationService,
    compensation_registry: CompensationRegistry,
) -> None:
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.COMPENSATING,
        error_message="boom",
        steps=[
            {
                "name": "a",
                "position": 0,
                "status": StepStatus.COMPENSATING,
                "compensation_handler": "demo.undo",
                "output_payload": {},
            }
        ],
    )
    step = workflow.steps[0]
    dangling = workflow_service.create_compensation_attempt(
        db_session, step.id, handler_name="demo.undo"
    )
    assert CompensationAttemptStatus(dangling.status) is CompensationAttemptStatus.RUNNING

    handler = RecordingCompensationHandler(output={"ok": True})
    compensation_registry.register("demo.undo", handler)

    result = compensation_service.resume_compensation(workflow.id)

    assert WorkflowStatus(result.status) is WorkflowStatus.COMPENSATED
    db_session.refresh(dangling)
    assert CompensationAttemptStatus(dangling.status) is CompensationAttemptStatus.FAILED
    assert dangling.error_type == "EXECUTION_INTERRUPTED"
    resumed_step = result.steps[0]
    assert len(resumed_step.compensation_attempts) == 2
    assert (
        CompensationAttemptStatus(resumed_step.compensation_attempts[-1].status)
        is CompensationAttemptStatus.SUCCEEDED
    )


def test_resume_compensation_a_missing_workflow_raises_not_found(
    db_session: Session, compensation_service: CompensationService
) -> None:
    with pytest.raises(WorkflowNotFoundError):
        compensation_service.resume_compensation("does-not-exist")


def test_resume_compensation_a_failed_workflow_is_rejected(
    db_session: Session, compensation_service: CompensationService
) -> None:
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.FAILED,
        error_message="boom",
        steps=[{"name": "a", "position": 0, "status": StepStatus.FAILED}],
    )
    with pytest.raises(InvalidCompensationStateError):
        compensation_service.resume_compensation(workflow.id)


def test_resume_compensation_claim_is_atomic_and_rejects_a_stale_version(
    db_session: Session,
) -> None:
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.COMPENSATING,
        error_message="boom",
        steps=[{"name": "a", "position": 0, "status": StepStatus.SUCCEEDED}],
    )
    won = workflow_service.claim_workflow_for_compensation_resume(
        db_session, workflow.id, expected_version=1
    )
    assert won is True

    lost = workflow_service.claim_workflow_for_compensation_resume(
        db_session, workflow.id, expected_version=1
    )
    assert lost is False


def test_resume_compensation_raises_conflict_error_when_claim_is_lost(
    db_session: Session,
    compensation_service: CompensationService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.COMPENSATING,
        error_message="boom",
        steps=[{"name": "a", "position": 0, "status": StepStatus.SUCCEEDED}],
    )
    monkeypatch.setattr(
        workflow_service, "claim_workflow_for_compensation_resume", lambda *a, **k: False
    )

    with pytest.raises(CompensationResumeConflictError):
        compensation_service.resume_compensation(workflow.id)


def test_resume_compensation_records_an_audit_event(
    db_session: Session,
    compensation_service: CompensationService,
    compensation_registry: CompensationRegistry,
) -> None:
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.COMPENSATING,
        error_message="boom",
        steps=[
            {
                "name": "a",
                "position": 0,
                "status": StepStatus.SUCCEEDED,
                "compensation_handler": "demo.undo",
                "output_payload": {},
            }
        ],
    )
    compensation_registry.register("demo.undo", RecordingCompensationHandler(output={}))

    compensation_service.resume_compensation(workflow.id)

    events = audit_service.list_events(db_session, workflow.id)
    event_types = [event.event_type for event in events]
    assert "workflow_compensation_resumed" in event_types


def test_resume_compensation_preserves_audit_chain_integrity(
    db_session: Session,
    compensation_service: CompensationService,
    compensation_registry: CompensationRegistry,
) -> None:
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.COMPENSATING,
        error_message="boom",
        steps=[
            {
                "name": "a",
                "position": 0,
                "status": StepStatus.COMPENSATING,
                "compensation_handler": "demo.undo",
                "output_payload": {},
            }
        ],
    )
    workflow_service.create_compensation_attempt(
        db_session, workflow.steps[0].id, handler_name="demo.undo"
    )
    compensation_registry.register("demo.undo", RecordingCompensationHandler(output={}))

    compensation_service.resume_compensation(workflow.id)

    result = verify_chain(db_session, workflow.id)
    assert result.valid is True


def test_resume_compensation_failure_preserves_original_failure_message(
    db_session: Session,
    compensation_service: CompensationService,
    compensation_registry: CompensationRegistry,
) -> None:
    workflow = build_workflow_in_status(
        db_session,
        workflow_status=WorkflowStatus.COMPENSATING,
        error_message="original execution failure",
        steps=[
            {
                "name": "a",
                "position": 0,
                "status": StepStatus.SUCCEEDED,
                "compensation_handler": "demo.undo",
                "output_payload": {},
            }
        ],
    )
    compensation_registry.register("demo.undo", FailingCompensationHandler())

    result = compensation_service.resume_compensation(workflow.id)

    assert WorkflowStatus(result.status) is WorkflowStatus.FAILED
    assert result.error_message == "original execution failure"
    assert result.compensation_summary is not None
    failed_step = result.compensation_summary["failed_compensation_step"]
    assert failed_step["step_id"] == workflow.steps[0].id
