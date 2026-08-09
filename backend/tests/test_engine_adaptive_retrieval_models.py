"""Tests for `app.engine.adaptive_retrieval.models.RetrievalObservation`:
construction, base-retrieval-eligibility enforcement, deterministic
identity, and query safety."""

from datetime import UTC, datetime

import pytest

from app.engine.adaptive_retrieval.errors import MalformedRetrievalObservationError
from app.engine.adaptive_retrieval.models import RetrievalObservation, compute_query_fingerprint

_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _observation(**overrides) -> RetrievalObservation:
    defaults = dict(
        query_fingerprint=compute_query_fingerprint("how do I fix the bug"),
        task_type="fix",
        repository_id="org/repo",
        retrieved_chunk_ids=("c1", "c2", "c3"),
        retrieved_chunk_content_hashes=("h1", "h2", "h3"),
        original_ranks=(1, 2, 3),
        original_scores=(0.9, 0.8, 0.7),
        selected_chunk_ids=("c1", "c2"),
        created_at=_CREATED_AT,
    )
    defaults.update(overrides)
    return RetrievalObservation(**defaults)


# --- construction / validation --------------------------------------------------------------


def test_valid_observation_constructs() -> None:
    obs = _observation()
    assert obs.task_type == "fix"
    assert obs.repository_id == "org/repo"
    assert obs.selected_chunk_ids == ("c1", "c2")


def test_blank_query_fingerprint_rejected() -> None:
    with pytest.raises(MalformedRetrievalObservationError, match="query_fingerprint"):
        _observation(query_fingerprint="   ")


def test_blank_task_type_rejected_if_provided() -> None:
    with pytest.raises(MalformedRetrievalObservationError, match="task_type"):
        _observation(task_type="  ")


def test_unsafe_repository_id_rejected() -> None:
    with pytest.raises(MalformedRetrievalObservationError, match="absolute filesystem path"):
        _observation(repository_id="/etc/passwd")
    with pytest.raises(MalformedRetrievalObservationError, match="absolute filesystem path"):
        _observation(repository_id="C:\\Windows\\System32")


def test_mismatched_parallel_tuple_lengths_rejected() -> None:
    with pytest.raises(MalformedRetrievalObservationError, match="same length"):
        _observation(retrieved_chunk_ids=("c1", "c2"))  # hashes/ranks/scores still length 3


def test_duplicate_retrieved_chunk_ids_rejected() -> None:
    with pytest.raises(MalformedRetrievalObservationError, match="duplicates"):
        _observation(
            retrieved_chunk_ids=("c1", "c1", "c3"),
            retrieved_chunk_content_hashes=("h1", "h1", "h3"),
            original_ranks=(1, 2, 3),
            original_scores=(0.9, 0.8, 0.7),
        )


def test_duplicate_selected_chunk_ids_rejected() -> None:
    with pytest.raises(MalformedRetrievalObservationError, match="duplicates"):
        _observation(selected_chunk_ids=("c1", "c1"))


# --- base-retrieval eligibility (critical structural invariant) -----------------------------


def test_selecting_a_chunk_never_retrieved_is_rejected() -> None:
    """Stage 7.5 cannot even construct an observation claiming a chunk was
    selected that Stage 6A's base retrieval did not return -- this is the
    hard, type-level enforcement of 'base retrieval remains authoritative'."""
    with pytest.raises(MalformedRetrievalObservationError, match="did not return"):
        _observation(selected_chunk_ids=("c1", "not-retrieved"))


def test_empty_selected_chunk_ids_is_valid() -> None:
    """Nothing selected (e.g. no chunk cleared context budget) is a valid,
    unremarkable observation."""
    obs = _observation(selected_chunk_ids=())
    assert obs.selected_chunk_ids == ()


# --- content_hash_for -------------------------------------------------------------------------


def test_content_hash_for_known_chunk() -> None:
    obs = _observation()
    assert obs.content_hash_for("c2") == "h2"


def test_content_hash_for_unknown_chunk_is_none() -> None:
    obs = _observation()
    assert obs.content_hash_for("never-retrieved") is None


# --- query safety ------------------------------------------------------------------------------


def test_query_fingerprint_is_deterministic() -> None:
    fp1 = compute_query_fingerprint("How do I fix the bug?")
    fp2 = compute_query_fingerprint("How do I fix the bug?")
    assert fp1 == fp2


def test_query_fingerprint_normalizes_case_and_whitespace() -> None:
    fp1 = compute_query_fingerprint("How Do I Fix   The Bug?")
    fp2 = compute_query_fingerprint("how do i fix the bug?")
    assert fp1 == fp2


def test_query_fingerprint_differs_for_different_queries() -> None:
    fp1 = compute_query_fingerprint("fix the bug")
    fp2 = compute_query_fingerprint("fix the feature")
    assert fp1 != fp2


def test_query_fingerprint_never_reveals_raw_text() -> None:
    fingerprint = compute_query_fingerprint("secret internal query text")
    assert "secret" not in fingerprint
    assert "internal" not in fingerprint
    assert len(fingerprint) == 64  # sha256 hex digest length


def test_observation_never_stores_raw_query_text() -> None:
    """No field on RetrievalObservation carries the original query string --
    only its fingerprint."""
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(RetrievalObservation)}
    assert "query" not in field_names
    assert "raw_query" not in field_names
    assert "prompt" not in field_names


# --- identity ------------------------------------------------------------------------------


def test_retrieval_id_is_deterministic() -> None:
    obs1 = _observation()
    obs2 = _observation()
    assert obs1.retrieval_id == obs2.retrieval_id


def test_retrieval_id_not_derived_from_random_uuid_or_timestamp() -> None:
    obs1 = _observation(created_at=datetime(2020, 1, 1, tzinfo=UTC))
    obs2 = _observation(created_at=datetime(2099, 12, 31, tzinfo=UTC))
    assert obs1.retrieval_id == obs2.retrieval_id


def test_retrieval_id_differs_by_selected_chunk_ids() -> None:
    obs1 = _observation(selected_chunk_ids=("c1",))
    obs2 = _observation(selected_chunk_ids=("c2",))
    assert obs1.retrieval_id != obs2.retrieval_id


def test_retrieval_id_differs_by_selection_order() -> None:
    """A differently-ordered context selection is a different semantic
    retrieval -- order is part of the identity."""
    obs1 = _observation(selected_chunk_ids=("c1", "c2"))
    obs2 = _observation(selected_chunk_ids=("c2", "c1"))
    assert obs1.retrieval_id != obs2.retrieval_id


def test_retrieval_id_differs_by_task_type() -> None:
    obs1 = _observation(task_type="fix")
    obs2 = _observation(task_type="doc_gen")
    assert obs1.retrieval_id != obs2.retrieval_id


def test_retrieval_id_differs_by_repository_id() -> None:
    obs1 = _observation(repository_id="org/repo-a")
    obs2 = _observation(repository_id="org/repo-b")
    assert obs1.retrieval_id != obs2.retrieval_id


def test_retrieval_id_differs_by_query_fingerprint() -> None:
    obs1 = _observation(query_fingerprint=compute_query_fingerprint("query one"))
    obs2 = _observation(query_fingerprint=compute_query_fingerprint("query two"))
    assert obs1.retrieval_id != obs2.retrieval_id
