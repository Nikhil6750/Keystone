"""Tests for SHA-256 hash-chain calculation of individual audit events."""

from datetime import UTC, datetime

from app.audit.hashing import (
    GENESIS_HASH,
    build_hash_envelope,
    compute_digest,
    compute_event_hash,
    format_timestamp,
)


def _envelope(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = dict(
        workflow_id="wf-1",
        sequence_number=1,
        event_type="workflow_created",
        actor_type="user",
        actor_id="api",
        step_id=None,
        execution_attempt_id=None,
        compensation_attempt_id=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        payload={"key": "value"},
        previous_hash=GENESIS_HASH,
    )
    base.update(overrides)
    return build_hash_envelope(**base)  # type: ignore[arg-type]


def test_genesis_hash_is_64_lowercase_zero_characters() -> None:
    assert GENESIS_HASH == "0" * 64
    assert len(GENESIS_HASH) == 64


def test_format_timestamp_is_stable_iso8601_utc() -> None:
    value = datetime(2026, 1, 1, 12, 30, 0, tzinfo=UTC)

    assert format_timestamp(value) == "2026-01-01T12:30:00+00:00"


def test_build_hash_envelope_excludes_event_hash_and_id() -> None:
    envelope = _envelope()

    assert "event_hash" not in envelope
    assert "id" not in envelope


def test_build_hash_envelope_includes_all_documented_fields() -> None:
    envelope = _envelope()

    expected_keys = {
        "workflow_id",
        "sequence_number",
        "event_type",
        "actor_type",
        "actor_id",
        "step_id",
        "execution_attempt_id",
        "compensation_attempt_id",
        "created_at",
        "payload",
        "previous_hash",
    }
    assert set(envelope.keys()) == expected_keys


def test_compute_event_hash_is_deterministic() -> None:
    envelope = _envelope()

    assert compute_event_hash(envelope) == compute_event_hash(envelope)


def test_compute_event_hash_is_64_character_lowercase_hex() -> None:
    result = compute_event_hash(_envelope())

    assert len(result) == 64
    assert result == result.lower()
    int(result, 16)  # raises ValueError if not valid hex


def test_compute_event_hash_changes_when_any_field_changes() -> None:
    base_hash = compute_event_hash(_envelope())

    assert compute_event_hash(_envelope(payload={"key": "different"})) != base_hash
    assert compute_event_hash(_envelope(sequence_number=2)) != base_hash
    assert compute_event_hash(_envelope(previous_hash="1" * 64)) != base_hash
    assert compute_event_hash(_envelope(actor_id="different")) != base_hash


def test_compute_digest_matches_canonical_sha256_of_value() -> None:
    import hashlib

    from app.audit.canonical import canonical_json

    value = {"result": "ok"}
    expected = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()

    assert compute_digest(value) == expected
