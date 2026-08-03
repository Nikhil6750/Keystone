"""Tests for the append-only audit-event service: sequencing and hash-chaining."""

import pytest
from sqlalchemy.orm import Session

from app.audit import service as audit_service
from app.audit.hashing import GENESIS_HASH
from app.audit.types import ActorType, AuditEventType
from app.schemas.workflow import WorkflowCreate
from app.services import workflow_service


def _create_workflow(db_session: Session) -> str:
    workflow = workflow_service.create_workflow(
        db_session, WorkflowCreate(name="demo", input_payload={}, steps=[])
    )
    return workflow.id


def test_first_event_links_to_genesis_hash(db_session: Session) -> None:
    workflow_id = _create_workflow(db_session)

    event = audit_service.append_event(
        db_session,
        workflow_id=workflow_id,
        event_type=AuditEventType.WORKFLOW_CREATED,
        actor_type=ActorType.USER,
        actor_id="api",
        payload={},
    )

    assert event.previous_hash == GENESIS_HASH
    assert event.sequence_number == 1


def test_sequence_numbers_increment_by_one(db_session: Session) -> None:
    workflow_id = _create_workflow(db_session)

    first = audit_service.append_event(
        db_session,
        workflow_id=workflow_id,
        event_type=AuditEventType.WORKFLOW_CREATED,
        actor_type=ActorType.USER,
        actor_id="api",
        payload={},
    )
    second = audit_service.append_event(
        db_session,
        workflow_id=workflow_id,
        event_type=AuditEventType.WORKFLOW_EXECUTION_STARTED,
        actor_type=ActorType.SYSTEM,
        actor_id="workflow_engine",
        payload={},
    )

    assert first.sequence_number == 1
    assert second.sequence_number == 2


def test_each_event_links_to_previous_events_hash(db_session: Session) -> None:
    workflow_id = _create_workflow(db_session)

    first = audit_service.append_event(
        db_session,
        workflow_id=workflow_id,
        event_type=AuditEventType.WORKFLOW_CREATED,
        actor_type=ActorType.USER,
        actor_id="api",
        payload={},
    )
    second = audit_service.append_event(
        db_session,
        workflow_id=workflow_id,
        event_type=AuditEventType.WORKFLOW_EXECUTION_STARTED,
        actor_type=ActorType.SYSTEM,
        actor_id="workflow_engine",
        payload={},
    )

    assert second.previous_hash == first.event_hash


def test_different_workflows_have_independent_chains(db_session: Session) -> None:
    workflow_a = _create_workflow(db_session)
    workflow_b = _create_workflow(db_session)

    event_a = audit_service.append_event(
        db_session,
        workflow_id=workflow_a,
        event_type=AuditEventType.WORKFLOW_CREATED,
        actor_type=ActorType.USER,
        actor_id="api",
        payload={},
    )
    event_b = audit_service.append_event(
        db_session,
        workflow_id=workflow_b,
        event_type=AuditEventType.WORKFLOW_CREATED,
        actor_type=ActorType.USER,
        actor_id="api",
        payload={},
    )

    assert event_a.sequence_number == 1
    assert event_b.sequence_number == 1
    assert event_a.previous_hash == GENESIS_HASH
    assert event_b.previous_hash == GENESIS_HASH


def test_oversized_payload_raises_value_error(db_session: Session) -> None:
    workflow_id = _create_workflow(db_session)

    with pytest.raises(ValueError, match="exceeds"):
        audit_service.append_event(
            db_session,
            workflow_id=workflow_id,
            event_type=AuditEventType.WORKFLOW_CREATED,
            actor_type=ActorType.USER,
            actor_id="api",
            payload={"blob": "x" * 100},
            max_payload_characters=10,
        )


def test_list_events_returns_events_in_sequence_order(db_session: Session) -> None:
    workflow_id = _create_workflow(db_session)
    for _ in range(3):
        audit_service.append_event(
            db_session,
            workflow_id=workflow_id,
            event_type=AuditEventType.WORKFLOW_EXECUTION_STARTED,
            actor_type=ActorType.SYSTEM,
            actor_id="workflow_engine",
            payload={},
        )

    events = audit_service.list_events(db_session, workflow_id)

    assert [e.sequence_number for e in events] == [1, 2, 3]


def test_list_events_rejects_out_of_range_limit(db_session: Session) -> None:
    workflow_id = _create_workflow(db_session)

    with pytest.raises(ValueError):
        audit_service.list_events(db_session, workflow_id, limit=0)
    with pytest.raises(ValueError):
        audit_service.list_events(db_session, workflow_id, limit=audit_service.MAX_LIST_LIMIT + 1)


def test_optional_correlation_ids_are_persisted_when_provided(db_session: Session) -> None:
    workflow_id = _create_workflow(db_session)

    event = audit_service.append_event(
        db_session,
        workflow_id=workflow_id,
        event_type=AuditEventType.STEP_SUCCEEDED,
        actor_type=ActorType.AGENT,
        actor_id="mock",
        step_id="step-1",
        execution_attempt_id="attempt-1",
        payload={},
    )

    assert event.step_id == "step-1"
    assert event.execution_attempt_id == "attempt-1"
    assert event.compensation_attempt_id is None
