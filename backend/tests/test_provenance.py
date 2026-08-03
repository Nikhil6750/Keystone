"""Tests for provenance tracing: `build_provenance`."""

from sqlalchemy.orm import Session

from app.audit import service as audit_service
from app.audit.types import ActorType, AuditEventType
from app.audit.verification import build_provenance
from app.schemas.workflow import WorkflowCreate
from app.services import workflow_service


def _create_workflow(db_session: Session) -> str:
    workflow = workflow_service.create_workflow(
        db_session, WorkflowCreate(name="demo", input_payload={}, steps=[])
    )
    return workflow.id


def test_provenance_shape_has_workflow_id_chain_valid_and_events(db_session: Session) -> None:
    workflow_id = _create_workflow(db_session)

    provenance = build_provenance(db_session, workflow_id)

    assert set(provenance.keys()) == {"workflow_id", "chain_valid", "events"}
    assert provenance["workflow_id"] == workflow_id


def test_provenance_for_workflow_with_no_events_is_empty_and_valid(db_session: Session) -> None:
    workflow_id = _create_workflow(db_session)

    provenance = build_provenance(db_session, workflow_id)

    assert provenance["chain_valid"] is True
    assert provenance["events"] == []


def test_provenance_events_are_ordered_by_sequence_number(db_session: Session) -> None:
    workflow_id = _create_workflow(db_session)
    for event_type in (
        AuditEventType.WORKFLOW_CREATED,
        AuditEventType.WORKFLOW_EXECUTION_STARTED,
        AuditEventType.WORKFLOW_SUCCEEDED,
    ):
        audit_service.append_event(
            db_session,
            workflow_id=workflow_id,
            event_type=event_type,
            actor_type=ActorType.SYSTEM,
            actor_id="workflow_engine",
            payload={},
        )

    provenance = build_provenance(db_session, workflow_id)

    sequence_numbers = [event.sequence_number for event in provenance["events"]]
    assert sequence_numbers == sorted(sequence_numbers)


def test_provenance_chain_valid_is_true_for_untampered_chain(db_session: Session) -> None:
    workflow_id = _create_workflow(db_session)
    audit_service.append_event(
        db_session,
        workflow_id=workflow_id,
        event_type=AuditEventType.WORKFLOW_CREATED,
        actor_type=ActorType.USER,
        actor_id="api",
        payload={},
    )

    provenance = build_provenance(db_session, workflow_id)

    assert provenance["chain_valid"] is True


def test_provenance_chain_valid_is_false_after_tampering(db_session: Session) -> None:
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

    provenance = build_provenance(db_session, workflow_id)

    assert provenance["chain_valid"] is False


def test_provenance_includes_step_and_attempt_correlation_ids(db_session: Session) -> None:
    workflow_id = _create_workflow(db_session)
    audit_service.append_event(
        db_session,
        workflow_id=workflow_id,
        event_type=AuditEventType.STEP_SUCCEEDED,
        actor_type=ActorType.AGENT,
        actor_id="mock",
        step_id="step-1",
        execution_attempt_id="attempt-1",
        payload={},
    )

    provenance = build_provenance(db_session, workflow_id)

    event = provenance["events"][0]
    assert event.step_id == "step-1"
    assert event.execution_attempt_id == "attempt-1"


def test_provenance_traces_full_lifecycle_across_multiple_event_types(db_session: Session) -> None:
    workflow_id = _create_workflow(db_session)
    for event_type, actor_type, actor_id in (
        (AuditEventType.WORKFLOW_CREATED, ActorType.USER, "api"),
        (AuditEventType.WORKFLOW_EXECUTION_STARTED, ActorType.SYSTEM, "workflow_engine"),
        (AuditEventType.WORKFLOW_FAILED, ActorType.SYSTEM, "workflow_engine"),
        (AuditEventType.WORKFLOW_COMPENSATION_STARTED, ActorType.SYSTEM, "workflow_engine"),
        (AuditEventType.WORKFLOW_COMPENSATED, ActorType.SYSTEM, "workflow_engine"),
    ):
        audit_service.append_event(
            db_session,
            workflow_id=workflow_id,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            payload={},
        )

    provenance = build_provenance(db_session, workflow_id)

    event_types = [event.event_type for event in provenance["events"]]
    assert event_types == [
        AuditEventType.WORKFLOW_CREATED,
        AuditEventType.WORKFLOW_EXECUTION_STARTED,
        AuditEventType.WORKFLOW_FAILED,
        AuditEventType.WORKFLOW_COMPENSATION_STARTED,
        AuditEventType.WORKFLOW_COMPENSATED,
    ]
    assert provenance["chain_valid"] is True
