"""Tests for the SQLAlchemy database layer: schema, constraints, and cascades."""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import StepAttempt, Workflow, WorkflowStep


def test_tables_are_created(db_engine: Engine) -> None:
    tables = set(inspect(db_engine).get_table_names())
    assert {"workflows", "workflow_steps", "step_attempts"} <= tables


def test_foreign_key_enforcement_is_active(db_engine: Engine) -> None:
    with db_engine.connect() as connection:
        result = connection.execute(text("PRAGMA foreign_keys")).scalar()
    assert result == 1


def test_workflow_persists_with_ordered_steps(db_session: Session) -> None:
    workflow = Workflow(name="demo", input_payload={})
    workflow.steps.append(
        WorkflowStep(name="second", position=1, agent_type="mock", input_payload={})
    )
    workflow.steps.append(
        WorkflowStep(name="first", position=0, agent_type="mock", input_payload={})
    )
    db_session.add(workflow)
    db_session.commit()
    db_session.expire_all()

    reloaded = db_session.get(Workflow, workflow.id)
    assert reloaded is not None
    assert [step.name for step in reloaded.steps] == ["first", "second"]


def test_deleting_workflow_cascades_to_steps_and_attempts(db_session: Session) -> None:
    workflow = Workflow(name="demo", input_payload={})
    step = WorkflowStep(name="step-1", position=0, agent_type="mock", input_payload={})
    step.attempts.append(StepAttempt(attempt_number=1))
    workflow.steps.append(step)
    db_session.add(workflow)
    db_session.commit()

    workflow_id = workflow.id
    step_id = step.id

    db_session.delete(workflow)
    db_session.commit()

    assert db_session.get(Workflow, workflow_id) is None
    assert db_session.get(WorkflowStep, step_id) is None
    assert db_session.query(StepAttempt).filter_by(step_id=step_id).count() == 0


def test_duplicate_step_positions_are_rejected(db_session: Session) -> None:
    workflow = Workflow(name="demo", input_payload={})
    workflow.steps.append(WorkflowStep(name="a", position=0, agent_type="mock", input_payload={}))
    workflow.steps.append(WorkflowStep(name="b", position=0, agent_type="mock", input_payload={}))
    db_session.add(workflow)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_duplicate_attempt_numbers_are_rejected(db_session: Session) -> None:
    workflow = Workflow(name="demo", input_payload={})
    step = WorkflowStep(name="a", position=0, agent_type="mock", input_payload={})
    step.attempts.append(StepAttempt(attempt_number=1))
    step.attempts.append(StepAttempt(attempt_number=1))
    workflow.steps.append(step)
    db_session.add(workflow)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_invalid_max_attempts_is_rejected(db_session: Session) -> None:
    workflow = Workflow(name="demo", input_payload={})
    workflow.steps.append(
        WorkflowStep(name="a", position=0, agent_type="mock", input_payload={}, max_attempts=0)
    )
    db_session.add(workflow)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_invalid_negative_position_is_rejected(db_session: Session) -> None:
    workflow = Workflow(name="demo", input_payload={})
    workflow.steps.append(WorkflowStep(name="a", position=-1, agent_type="mock", input_payload={}))
    db_session.add(workflow)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
