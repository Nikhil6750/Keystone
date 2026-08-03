"""SHA-256 hash-chain calculation for audit events.

Tamper-evident, not tamper-proof: a chain break proves *something* in the
persisted history was altered after the fact, but this is plain hash
chaining — it carries no digital signature, no external notarization, and no
protection against someone with direct database write access recomputing the
entire chain from scratch. `cryptography`/asymmetric signing is intentionally
not used in this same-day prototype; `hashlib.sha256` (standard library) is
sufficient to demonstrate tamper evidence for a local SQLite audit log.
"""

import hashlib
from datetime import UTC, datetime
from typing import Any

from app.audit.canonical import canonical_json

GENESIS_HASH = "0" * 64


def format_timestamp(value: datetime) -> str:
    """A stable ISO-8601 UTC representation, used both for hashing and audit payloads.

    SQLite drops tzinfo on round-trip: a `datetime.now(UTC)` value written at
    append time comes back naive after a fresh query. Every `created_at` this
    application produces is already UTC (see `app.audit.service.append_event`),
    so a naive value here means "UTC, tzinfo lost in storage" rather than
    local time — treating it as local time would silently shift the hash
    input and break verification for events that were never tampered with.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def build_hash_envelope(
    *,
    workflow_id: str,
    sequence_number: int,
    event_type: str,
    actor_type: str,
    actor_id: str,
    step_id: str | None,
    execution_attempt_id: str | None,
    compensation_attempt_id: str | None,
    created_at: datetime,
    payload: dict[str, Any],
    previous_hash: str,
) -> dict[str, Any]:
    """The exact, documented set of fields hashed for one audit event.

    Deliberately excludes the event's own `event_hash` and its database
    primary key `id` — a hash must never hash itself, and the envelope must
    be reproducible from the event's own recorded fields.
    """
    return {
        "workflow_id": workflow_id,
        "sequence_number": sequence_number,
        "event_type": event_type,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "step_id": step_id,
        "execution_attempt_id": execution_attempt_id,
        "compensation_attempt_id": compensation_attempt_id,
        "created_at": format_timestamp(created_at),
        "payload": payload,
        "previous_hash": previous_hash,
    }


def compute_event_hash(envelope: dict[str, Any]) -> str:
    """The lowercase hex SHA-256 digest of `envelope`'s canonical JSON serialization."""
    digest = hashlib.sha256(canonical_json(envelope).encode("utf-8"))
    return digest.hexdigest()


def compute_digest(value: Any) -> str:
    """A lowercase hex SHA-256 digest of `value`'s canonical JSON serialization.

    Used to represent a potentially large input/output in an audit payload
    without storing the full content (see `output_digest`/`input_digest`).
    """
    digest = hashlib.sha256(canonical_json(value).encode("utf-8"))
    return digest.hexdigest()
