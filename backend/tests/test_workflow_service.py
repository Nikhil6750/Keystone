"""Tests for the workflow persistence service."""

from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.engine.state_machine import InvalidStateTransition
from app.models.enums import AttemptStatus, StepStatus, WorkflowStatus
from app.schemas.workflow import WorkflowCreate, WorkflowStepCreate
from app.services import workflow_service


def _workflow_create(**overrides: Any) -> WorkflowCreate:
    data: dict[str, Any] = {
        "name": "demo-workflow",
        "input_payload": {"key": "value"},
        "steps": [
            WorkflowStepCreate(name="step-a", position=0, agent_type="mock"),
            WorkflowStepCreate(name="step-b", position=1, agent_type="mock"),
        ],
    }
    data.update(overrides)
    return WorkflowCreate(**data)


def test_create_workflow_persists_workflow_and_steps_in_one_transaction(
    db_session: Session,
) -> None:
    workflow = workflow_service.create_workflow(db_session, _workflow_create())

    assert workflow.id is not None
    assert len(workflow.steps) == 2
    assert workflow.status == WorkflowStatus.PENDING


def test_invalid_step_data_rolls_back_entire_workflow(db_session: Session) -> None:
    # WorkflowCreate itself rejects duplicate positions (see schema tests), so to exercise
    # the service's own transactional rollback we bypass schema validation with
    # model_construct() and rely on the database's uniqueness constraint instead.
    duplicate_position_step = WorkflowStepCreate(name="dup", position=0, agent_type="mock")
    data = WorkflowCreate.model_construct(
        name="demo-workflow",
        description=None,
        input_payload={},
        steps=[duplicate_position_step, duplicate_position_step.model_copy()],
    )

    with pytest.raises(IntegrityError):
        workflow_service.create_workflow(db_session, data)

    assert workflow_service.list_workflows(db_session) == []


def test_workflow_retrieval_returns_ordered_steps(db_session: Session) -> None:
    created = workflow_service.create_workflow(
        db_session,
        _workflow_create(
            steps=[
                WorkflowStepCreate(name="second", position=1, agent_type="mock"),
                WorkflowStepCreate(name="first", position=0, agent_type="mock"),
            ]
        ),
    )

    fetched = workflow_service.get_workflow(db_session, created.id)

    assert fetched is not None
    assert [step.name for step in fetched.steps] == ["first", "second"]


def test_missing_workflow_retrieval_returns_none(db_session: Session) -> None:
    assert workflow_service.get_workflow(db_session, "does-not-exist") is None


def test_workflow_listing_applies_ordering_and_limit(db_session: Session) -> None:
    for name in ("first", "second", "third"):
        workflow_service.create_workflow(db_session, _workflow_create(name=name, steps=[]))

    results = workflow_service.list_workflows(db_session, limit=2)

    assert len(results) == 2
    assert results[0].created_at >= results[1].created_at


def test_invalid_listing_limit_is_rejected(db_session: Session) -> None:
    with pytest.raises(ValueError, match="limit"):
        workflow_service.list_workflows(db_session, limit=0)


def test_step_attempts_increment_correctly(db_session: Session) -> None:
    workflow = workflow_service.create_workflow(db_session, _workflow_create())
    step = workflow.steps[0]

    first_attempt = workflow_service.create_step_attempt(db_session, step.id)
    second_attempt = workflow_service.create_step_attempt(db_session, step.id)

    assert first_attempt.attempt_number == 1
    assert second_attempt.attempt_number == 2

    refreshed = workflow_service.get_workflow(db_session, workflow.id)
    assert refreshed is not None
    refreshed_step = next(s for s in refreshed.steps if s.id == step.id)
    assert refreshed_step.attempt_count == 2


def test_attempt_success_information_is_stored(db_session: Session) -> None:
    workflow = workflow_service.create_workflow(db_session, _workflow_create())
    step = workflow.steps[0]
    attempt = workflow_service.create_step_attempt(db_session, step.id)

    completed = workflow_service.complete_step_attempt(
        db_session, attempt.id, status=AttemptStatus.SUCCEEDED, output_payload={"result": "ok"}
    )

    assert completed.status == AttemptStatus.SUCCEEDED
    assert completed.output_payload == {"result": "ok"}
    assert completed.completed_at is not None
    assert completed.error_message is None


def test_attempt_failure_information_is_stored(db_session: Session) -> None:
    workflow = workflow_service.create_workflow(db_session, _workflow_create())
    step = workflow.steps[0]
    attempt = workflow_service.create_step_attempt(db_session, step.id)

    completed = workflow_service.complete_step_attempt(
        db_session,
        attempt.id,
        status=AttemptStatus.FAILED,
        error_type="TimeoutError",
        error_message="agent timed out",
    )

    assert completed.status == AttemptStatus.FAILED
    assert completed.error_type == "TimeoutError"
    assert completed.error_message == "agent timed out"


def test_invalid_workflow_state_transition_is_rolled_back(db_session: Session) -> None:
    workflow = workflow_service.create_workflow(db_session, _workflow_create())

    with pytest.raises(InvalidStateTransition):
        workflow_service.transition_workflow(db_session, workflow.id, WorkflowStatus.SUCCEEDED)

    reloaded = workflow_service.get_workflow(db_session, workflow.id)
    assert reloaded is not None
    assert reloaded.status == WorkflowStatus.PENDING
    assert reloaded.version == 1


def test_workflow_transition_persists_valid_change(db_session: Session) -> None:
    workflow = workflow_service.create_workflow(db_session, _workflow_create())

    updated = workflow_service.transition_workflow(db_session, workflow.id, WorkflowStatus.RUNNING)

    assert updated.status == WorkflowStatus.RUNNING
    assert updated.started_at is not None


def test_step_transition_persists_valid_change(db_session: Session) -> None:
    workflow = workflow_service.create_workflow(db_session, _workflow_create())
    step = workflow.steps[0]

    updated = workflow_service.transition_step(db_session, step.id, StepStatus.RUNNING)

    assert updated.status == StepStatus.RUNNING
    assert updated.started_at is not None
