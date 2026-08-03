"""Tests for tamper-evident audit-chain verification."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.audit import service as audit_service
from app.audit.hashing import GENESIS_HASH, build_hash_envelope, compute_event_hash
from app.audit.types import ActorType, AuditEventType
from app.audit.verification import verify_chain, verify_event_sequence
from app.models.audit_event import AuditEvent
from app.schemas.workflow import WorkflowCreate
from app.services import workflow_service


def _create_workflow(db_session: Session) -> str:
    workflow = workflow_service.create_workflow(
        db_session, WorkflowCreate(name="demo", input_payload={}, steps=[])
    )
    return workflow.id


def _valid_event(
    *, workflow_id: str, sequence_number: int, previous_hash: str, payload: dict[str, object]
) -> AuditEvent:
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    envelope = build_hash_envelope(
        workflow_id=workflow_id,
        sequence_number=sequence_number,
        event_type=AuditEventType.WORKFLOW_CREATED.value,
        actor_type=ActorType.USER.value,
        actor_id="api",
        step_id=None,
        execution_attempt_id=None,
        compensation_attempt_id=None,
        created_at=created_at,
        payload=payload,
        previous_hash=previous_hash,
    )
    return AuditEvent(
        workflow_id=workflow_id,
        sequence_number=sequence_number,
        event_type=AuditEventType.WORKFLOW_CREATED,
        actor_type=ActorType.USER,
        actor_id="api",
        payload=payload,
        previous_hash=previous_hash,
        event_hash=compute_event_hash(envelope),
        created_at=created_at,
    )


def test_empty_chain_is_valid() -> None:
    result = verify_event_sequence("wf-1", [])

    assert result.valid is True
    assert result.event_count == 0
    assert result.first_invalid_sequence is None


def test_well_formed_chain_is_valid() -> None:
    first = _valid_event(
        workflow_id="wf-1", sequence_number=1, previous_hash=GENESIS_HASH, payload={"a": 1}
    )
    second = _valid_event(
        workflow_id="wf-1", sequence_number=2, previous_hash=first.event_hash, payload={"b": 2}
    )

    result = verify_event_sequence("wf-1", [first, second])

    assert result.valid is True
    assert result.event_count == 2


def test_duplicate_sequence_number_is_detected() -> None:
    first = _valid_event(
        workflow_id="wf-1", sequence_number=1, previous_hash=GENESIS_HASH, payload={}
    )
    duplicate = _valid_event(
        workflow_id="wf-1", sequence_number=1, previous_hash=first.event_hash, payload={}
    )

    result = verify_event_sequence("wf-1", [first, duplicate])

    assert result.valid is False
    assert result.first_invalid_sequence == 1


def test_gap_in_sequence_numbers_is_detected() -> None:
    first = _valid_event(
        workflow_id="wf-1", sequence_number=1, previous_hash=GENESIS_HASH, payload={}
    )
    skipped = _valid_event(
        workflow_id="wf-1", sequence_number=3, previous_hash=first.event_hash, payload={}
    )

    result = verify_event_sequence("wf-1", [first, skipped])

    assert result.valid is False
    assert result.first_invalid_sequence == 3


def test_broken_previous_hash_link_is_detected() -> None:
    first = _valid_event(
        workflow_id="wf-1", sequence_number=1, previous_hash=GENESIS_HASH, payload={}
    )
    second = _valid_event(workflow_id="wf-1", sequence_number=2, previous_hash="1" * 64, payload={})

    result = verify_event_sequence("wf-1", [first, second])

    assert result.valid is False
    assert result.first_invalid_sequence == 2
    assert result.reason is not None


def test_tampered_event_hash_is_detected() -> None:
    first = _valid_event(
        workflow_id="wf-1", sequence_number=1, previous_hash=GENESIS_HASH, payload={}
    )
    first.event_hash = "f" * 64

    result = verify_event_sequence("wf-1", [first])

    assert result.valid is False
    assert result.first_invalid_sequence == 1


def test_first_invalid_sequence_reports_earliest_break_not_a_later_one() -> None:
    first = _valid_event(
        workflow_id="wf-1", sequence_number=1, previous_hash=GENESIS_HASH, payload={}
    )
    first.payload = {"tampered": True}  # invalidates first's own hash
    second = _valid_event(
        workflow_id="wf-1", sequence_number=2, previous_hash=first.event_hash, payload={}
    )

    result = verify_event_sequence("wf-1", [first, second])

    assert result.first_invalid_sequence == 1


def test_verify_chain_on_freshly_appended_events_is_valid(db_session: Session) -> None:
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

    result = verify_chain(db_session, workflow_id)

    assert result.valid is True
    assert result.event_count == 3


def test_verify_chain_detects_directly_modified_payload(db_session: Session) -> None:
    workflow_id = _create_workflow(db_session)
    event = audit_service.append_event(
        db_session,
        workflow_id=workflow_id,
        event_type=AuditEventType.WORKFLOW_CREATED,
        actor_type=ActorType.USER,
        actor_id="api",
        payload={"original": True},
    )
    event.payload = {"tampered": True}
    db_session.commit()

    result = verify_chain(db_session, workflow_id)

    assert result.valid is False
    assert result.first_invalid_sequence == 1


def test_verify_chain_on_workflow_with_no_events_is_valid(db_session: Session) -> None:
    workflow_id = _create_workflow(db_session)

    result = verify_chain(db_session, workflow_id)

    assert result.valid is True
    assert result.event_count == 0
