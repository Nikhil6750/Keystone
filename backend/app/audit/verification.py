"""Audit-chain verification and provenance tracing.

Verification is tamper-*evident*: it proves whether the persisted chain is
internally consistent with the recorded hashes, not that the data was never
altered by someone with direct database access and the ability to
recompute the whole chain. There is no external notarization here.
"""

import hmac
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.hashing import GENESIS_HASH, build_hash_envelope, compute_event_hash
from app.audit.service import MAX_LIST_LIMIT, list_events
from app.models.audit_event import AuditEvent


@dataclass(frozen=True)
class ChainVerificationResult:
    """A safe, API-facing chain-verification outcome. Never exposes canonical hash input."""

    workflow_id: str
    valid: bool
    event_count: int
    first_invalid_sequence: int | None
    reason: str | None


def _all_events(db: Session, workflow_id: str) -> list[AuditEvent]:
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.workflow_id == workflow_id)
        .order_by(AuditEvent.sequence_number)
    )
    return list(db.scalars(stmt).all())


def verify_event_sequence(workflow_id: str, events: list[AuditEvent]) -> ChainVerificationResult:
    """Pure verification logic over an already-fetched, sequence-ordered event list.

    Separated from `verify_chain` so tests can exercise malformed histories
    (e.g. a duplicate or missing sequence number) using plain unpersisted
    `AuditEvent` objects, without needing to bypass the database's own
    uniqueness constraints.
    """
    if not events:
        return ChainVerificationResult(
            workflow_id=workflow_id,
            valid=True,
            event_count=0,
            first_invalid_sequence=None,
            reason=None,
        )

    expected_sequence = 1
    expected_previous_hash = GENESIS_HASH
    for event in events:
        if event.sequence_number != expected_sequence:
            return ChainVerificationResult(
                workflow_id=workflow_id,
                valid=False,
                event_count=len(events),
                first_invalid_sequence=event.sequence_number,
                reason="Sequence number is not contiguous",
            )
        if not hmac.compare_digest(event.previous_hash, expected_previous_hash):
            return ChainVerificationResult(
                workflow_id=workflow_id,
                valid=False,
                event_count=len(events),
                first_invalid_sequence=event.sequence_number,
                reason="Previous-hash link mismatch",
            )
        envelope = build_hash_envelope(
            workflow_id=event.workflow_id,
            sequence_number=event.sequence_number,
            event_type=event.event_type.value,
            actor_type=event.actor_type.value,
            actor_id=event.actor_id,
            step_id=event.step_id,
            execution_attempt_id=event.execution_attempt_id,
            compensation_attempt_id=event.compensation_attempt_id,
            created_at=event.created_at,
            payload=event.payload,
            previous_hash=event.previous_hash,
        )
        expected_hash = compute_event_hash(envelope)
        if not hmac.compare_digest(expected_hash, event.event_hash):
            return ChainVerificationResult(
                workflow_id=workflow_id,
                valid=False,
                event_count=len(events),
                first_invalid_sequence=event.sequence_number,
                reason="Event hash mismatch",
            )
        expected_previous_hash = event.event_hash
        expected_sequence += 1

    return ChainVerificationResult(
        workflow_id=workflow_id,
        valid=True,
        event_count=len(events),
        first_invalid_sequence=None,
        reason=None,
    )


def verify_chain(db: Session, workflow_id: str) -> ChainVerificationResult:
    """Verify `workflow_id`'s full persisted audit chain.

    Stops at the first invalid event found; does not collect every
    subsequent discrepancy.
    """
    return verify_event_sequence(workflow_id, _all_events(db, workflow_id))


def build_provenance(db: Session, workflow_id: str) -> dict[str, Any]:
    """Build an ordered provenance trace for `workflow_id`, including chain validity."""
    events = list_events(db, workflow_id, limit=MAX_LIST_LIMIT)
    verification = verify_chain(db, workflow_id)
    return {
        "workflow_id": workflow_id,
        "chain_valid": verification.valid,
        "events": events,
    }
