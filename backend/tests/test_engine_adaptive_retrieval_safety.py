"""Stage 7.5 SAFETY tests: no reasoning-shaped or credential-shaped field
anywhere in the module, no raw query/prompt text, no open
`dict[str, Any]`/`Any` field, and no raw traceback/absolute-path leakage."""

import dataclasses
from datetime import UTC, datetime

import pytest

from app.engine.adaptive_retrieval.errors import MalformedRetrievalObservationError
from app.engine.adaptive_retrieval.feedback import RetrievalFeedback
from app.engine.adaptive_retrieval.models import RetrievalObservation, compute_query_fingerprint
from app.engine.adaptive_retrieval.passport import RetrievalBucket, RetrievalPassport
from app.engine.adaptive_retrieval.policy import AdaptiveRetrievalPolicy
from app.engine.adaptive_retrieval.reranking import RankedResult
from app.engine.adaptive_retrieval.scoring import SelectedEvidence

_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)

_FORBIDDEN_FIELD_NAME_SUBSTRINGS = (
    "password",
    "credential",
    "secret",
    "access_token",
    "session_token",
    "chain_of_thought",
    "reasoning",
    "internal_thought",
    "hidden_prompt",
    "raw_prompt",
    "scratchpad",
    "quality",
    "intelligence",
    "traceback",
    "stack_trace",
    "raw_query",
)

_STAGE_75_DATACLASSES = (
    RetrievalObservation,
    RetrievalFeedback,
    RetrievalBucket,
    RetrievalPassport,
    AdaptiveRetrievalPolicy,
    SelectedEvidence,
)


def test_no_stage75_dataclass_has_a_forbidden_field_name() -> None:
    offenders: list[str] = []
    for cls in _STAGE_75_DATACLASSES:
        for f in dataclasses.fields(cls):
            lowered = f.name.lower()
            if any(bad in lowered for bad in _FORBIDDEN_FIELD_NAME_SUBSTRINGS):
                offenders.append(f"{cls.__name__}.{f.name}")
    assert offenders == []


def test_no_raw_query_field_anywhere() -> None:
    """Only `query_fingerprint` may exist -- never `query`/`raw_query`/
    `prompt`/`text` carrying the original user-supplied query string."""
    forbidden_query_names = {"query", "prompt", "text", "raw_text"}
    offenders: list[str] = []
    for cls in (RetrievalObservation, RetrievalFeedback):
        for f in dataclasses.fields(cls):
            if f.name in forbidden_query_names:
                offenders.append(f"{cls.__name__}.{f.name}")
    assert offenders == []


def test_no_open_any_or_unbounded_dict_field_on_core_types() -> None:
    """Every field is a scalar, tuple of scalars, or typed enum member --
    no `dict[str, Any]`/`Any` field exists for unrestricted arbitrary
    metadata to hide in."""
    offenders: list[str] = []
    for cls in (RetrievalObservation, RetrievalFeedback, AdaptiveRetrievalPolicy):
        for f in dataclasses.fields(cls):
            type_str = str(f.type)
            if "Any" in type_str or "dict[str, Any]" in type_str.replace(" ", ""):
                offenders.append(f"{cls.__name__}.{f.name}: {type_str}")
    assert offenders == []


def test_query_fingerprint_of_sensitive_text_reveals_nothing() -> None:
    fingerprint = compute_query_fingerprint(
        "chain of thought: the secret credential is sk-abcdef123456"
    )
    assert "secret" not in fingerprint
    assert "credential" not in fingerprint
    assert "sk-abcdef123456" not in fingerprint


def test_observation_rejects_unsafe_repository_path() -> None:
    with pytest.raises(MalformedRetrievalObservationError, match="absolute filesystem path"):
        RetrievalObservation(
            query_fingerprint=compute_query_fingerprint("q"),
            repository_id="/home/user/.env",
        )


def test_feedback_construction_never_requires_raw_exception_text() -> None:
    """RetrievalFeedback has no field that could carry a raw
    traceback/exception message -- only typed, already-safe status enums."""
    field_names = {f.name for f in dataclasses.fields(RetrievalFeedback)}
    assert "error" not in field_names
    assert "exception" not in field_names
    assert "failure_reason" not in field_names


def test_ranked_result_carries_no_new_unsafe_field() -> None:
    field_names = {f.name for f in dataclasses.fields(RankedResult)}
    assert field_names == {"result", "base_score", "adjustment", "evidence"}
