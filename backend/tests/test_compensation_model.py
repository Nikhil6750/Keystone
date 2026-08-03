"""Tests for the `CompensationAttempt` model and its persistence constraints."""

import pytest
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.compensation_attempt import CompensationAttempt
from app.models.enums import CompensationAttemptStatus
from app.models.workflow import Workflow
from app.models.workflow_step import WorkflowStep


def test_compensation_attempt_table_is_created(db_engine: Engine) -> None:
    tables = set(inspect(db_engine).get_table_names())
    assert "compensation_attempts" in tables


def test_workflow_deletion_cascades_to_compensation_attempts(db_session: Session) -> None:
    workflow = Workflow(name="demo", input_payload={})
    step = WorkflowStep(name="step-1", position=0, agent_type="mock", input_payload={})
    step.compensation_attempts.append(
        CompensationAttempt(attempt_number=1, handler_name="demo.undo")
    )
    workflow.steps.append(step)
    db_session.add(workflow)
    db_session.commit()

    step_id = step.id
    db_session.delete(workflow)
    db_session.commit()

    assert db_session.query(CompensationAttempt).filter_by(step_id=step_id).count() == 0


def test_duplicate_compensation_attempt_numbers_are_rejected(db_session: Session) -> None:
    workflow = Workflow(name="demo", input_payload={})
    step = WorkflowStep(name="step-1", position=0, agent_type="mock", input_payload={})
    step.compensation_attempts.append(
        CompensationAttempt(attempt_number=1, handler_name="demo.undo")
    )
    step.compensation_attempts.append(
        CompensationAttempt(attempt_number=1, handler_name="demo.undo")
    )
    workflow.steps.append(step)
    db_session.add(workflow)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_invalid_attempt_number_is_rejected(db_session: Session) -> None:
    workflow = Workflow(name="demo", input_payload={})
    step = WorkflowStep(name="step-1", position=0, agent_type="mock", input_payload={})
    step.compensation_attempts.append(
        CompensationAttempt(attempt_number=0, handler_name="demo.undo")
    )
    workflow.steps.append(step)
    db_session.add(workflow)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_status_defaults_to_running(db_session: Session) -> None:
    workflow = Workflow(name="demo", input_payload={})
    step = WorkflowStep(name="step-1", position=0, agent_type="mock", input_payload={})
    step.compensation_attempts.append(
        CompensationAttempt(attempt_number=1, handler_name="demo.undo")
    )
    workflow.steps.append(step)
    db_session.add(workflow)
    db_session.commit()

    assert step.compensation_attempts[0].status == CompensationAttemptStatus.RUNNING


def test_timestamps_are_timezone_aware_utc(db_session: Session) -> None:
    workflow = Workflow(name="demo", input_payload={})
    step = WorkflowStep(name="step-1", position=0, agent_type="mock", input_payload={})
    step.compensation_attempts.append(
        CompensationAttempt(attempt_number=1, handler_name="demo.undo")
    )
    workflow.steps.append(step)
    db_session.add(workflow)
    db_session.commit()

    attempt = step.compensation_attempts[0]
    assert attempt.started_at.tzinfo is not None
    assert attempt.created_at.tzinfo is not None
