"""Append-only audit-event service: sequencing, hash-chaining, and retrieval.

`append_event` is the only way an `AuditEvent` is ever created; nothing in the
application updates or individually deletes one afterward.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.audit.canonical import canonical_json
from app.audit.hashing import GENESIS_HASH, build_hash_envelope, compute_event_hash
from app.audit.types import ActorType, AuditEventType
from app.models.audit_event import AuditEvent

logger = logging.getLogger(__name__)

_MAX_SEQUENCE_RETRIES = 5
MAX_LIST_LIMIT = 500
DEFAULT_MAX_PAYLOAD_CHARACTERS = 5000


def _last_event(db: Session, workflow_id: str) -> AuditEvent | None:
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.workflow_id == workflow_id)
        .order_by(AuditEvent.sequence_number.desc())
        .limit(1)
    )
    return db.scalars(stmt).one_or_none()


def append_event(
    db: Session,
    *,
    workflow_id: str,
    event_type: AuditEventType,
    actor_type: ActorType,
    actor_id: str,
    step_id: str | None = None,
    execution_attempt_id: str | None = None,
    compensation_attempt_id: str | None = None,
    payload: dict[str, Any],
    max_payload_characters: int = DEFAULT_MAX_PAYLOAD_CHARACTERS,
) -> AuditEvent:
    """Append the next event in `workflow_id`'s audit chain.

    Allocates the next sequence number and hash-links to the previous event
    (or the genesis hash for the first event). Retries a bounded number of
    times only when a concurrent append raced for the same sequence number
    (a `UNIQUE(workflow_id, sequence_number)` conflict); never silently drops
    an event — if every retry is exhausted, the last database error is
    re-raised rather than swallowed.

    Raises `ValueError` if `payload`'s canonical JSON exceeds
    `max_payload_characters` — callers must summarize or digest large values
    (see `app.audit.hashing.compute_digest`) rather than embedding them whole.
    """
    if len(canonical_json(payload)) > max_payload_characters:
        raise ValueError(f"audit payload exceeds {max_payload_characters} characters")

    last_error: SQLAlchemyError | None = None
    for _attempt in range(_MAX_SEQUENCE_RETRIES):
        last = _last_event(db, workflow_id)
        sequence_number = 1 if last is None else last.sequence_number + 1
        previous_hash = GENESIS_HASH if last is None else last.event_hash
        created_at = datetime.now(UTC)

        envelope = build_hash_envelope(
            workflow_id=workflow_id,
            sequence_number=sequence_number,
            event_type=event_type.value,
            actor_type=actor_type.value,
            actor_id=actor_id,
            step_id=step_id,
            execution_attempt_id=execution_attempt_id,
            compensation_attempt_id=compensation_attempt_id,
            created_at=created_at,
            payload=payload,
            previous_hash=previous_hash,
        )
        event_hash = compute_event_hash(envelope)

        event = AuditEvent(
            workflow_id=workflow_id,
            step_id=step_id,
            execution_attempt_id=execution_attempt_id,
            compensation_attempt_id=compensation_attempt_id,
            sequence_number=sequence_number,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            payload=payload,
            previous_hash=previous_hash,
            event_hash=event_hash,
            created_at=created_at,
        )
        db.add(event)
        try:
            db.commit()
        except SQLAlchemyError as exc:
            db.rollback()
            last_error = exc
            logger.warning(
                "audit_event_sequence_conflict workflow_id=%s sequence_number=%s",
                workflow_id,
                sequence_number,
            )
            continue
        return event

    assert last_error is not None  # loop always executes at least once
    raise last_error


def list_events(db: Session, workflow_id: str, limit: int = 100) -> list[AuditEvent]:
    """List a workflow's audit events in sequence order, bounded by `limit`."""
    if limit <= 0 or limit > MAX_LIST_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIST_LIMIT}")
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.workflow_id == workflow_id)
        .order_by(AuditEvent.sequence_number)
        .limit(limit)
    )
    return list(db.scalars(stmt).all())
