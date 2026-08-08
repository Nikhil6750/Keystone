"""Tests for `app.engine.adaptive_retrieval.passport`: per-chunk aggregate
evidence, the verified-success denominator, the task/repository/repository
+task hierarchy, rebuildability from raw feedback, order-independence, and
the stale-content guard."""

import random
from datetime import UTC, datetime

from app.contracts.enums import AgentExecutionStatus
from app.contracts.verification import VerificationStatus
from app.engine.adaptive_retrieval.feedback import RetrievalFeedback
from app.engine.adaptive_retrieval.passport import (
    rebuild_all_retrieval_passports,
    rebuild_retrieval_passport,
)

_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _feedback(
    *,
    retrieval_id: str,
    chunk_ids: tuple[str, ...] = ("chunk-1",),
    verification_status: VerificationStatus = VerificationStatus.PASSED,
    task_type: str | None = "fix",
    repository_id: str | None = "org/repo",
    agent_type: str | None = None,
    chunk_content_hashes: tuple[str, ...] = (),
) -> RetrievalFeedback:
    return RetrievalFeedback(
        retrieval_id=retrieval_id,
        chunk_ids=chunk_ids,
        verification_status=verification_status,
        task_type=task_type,
        repository_id=repository_id,
        agent_type=agent_type,
        execution_status=AgentExecutionStatus.SUCCEEDED,
        chunk_content_hashes=chunk_content_hashes,
        created_at=_CREATED_AT,
    )


# --- counts / verified-success denominator ---------------------------------------------------


def test_passport_counts_and_rate() -> None:
    feedback = [
        _feedback(retrieval_id="r1", verification_status=VerificationStatus.PASSED),
        _feedback(retrieval_id="r2", verification_status=VerificationStatus.FAILED),
        _feedback(retrieval_id="r3", verification_status=VerificationStatus.INCONCLUSIVE),
        _feedback(retrieval_id="r4", verification_status=VerificationStatus.REQUIRES_HUMAN_REVIEW),
    ]
    passport = rebuild_retrieval_passport(feedback, chunk_id="chunk-1")
    v = passport.overall.verification
    assert v.verified_success_count == 1
    assert v.verification_failure_count == 1
    assert v.verification_inconclusive_count == 1
    assert v.human_review_count == 1
    assert v.verification_sample_count == 4
    assert v.verified_success_rate == 0.25
    assert passport.overall.retrieval_count == 4
    assert passport.overall.selected_count == 4


def test_passport_zero_samples_has_none_rate_never_zero() -> None:
    passport = rebuild_retrieval_passport([], chunk_id="chunk-1")
    assert passport.overall.verification.verification_sample_count == 0
    assert passport.overall.verification.verified_success_rate is None


def test_passport_only_counts_feedback_referencing_the_chunk() -> None:
    feedback = [
        _feedback(retrieval_id="r1", chunk_ids=("chunk-1",)),
        _feedback(retrieval_id="r2", chunk_ids=("chunk-2",)),
    ]
    passport = rebuild_retrieval_passport(feedback, chunk_id="chunk-1")
    assert passport.overall.verification.verification_sample_count == 1


def test_shared_attribution_counts_all_selected_chunks_equally() -> None:
    """One feedback record naming multiple chunks contributes the same
    verification signal to each -- weak, non-causal, shared attribution."""
    feedback = [_feedback(retrieval_id="r1", chunk_ids=("chunk-1", "chunk-2", "chunk-3"))]
    p1 = rebuild_retrieval_passport(feedback, chunk_id="chunk-1")
    p2 = rebuild_retrieval_passport(feedback, chunk_id="chunk-2")
    p3 = rebuild_retrieval_passport(feedback, chunk_id="chunk-3")
    assert p1.overall.verification.verified_success_count == 1
    assert p2.overall.verification.verified_success_count == 1
    assert p3.overall.verification.verified_success_count == 1


# --- hierarchy: task / repository / repository+task / agent ---------------------------------


def test_task_type_bucket() -> None:
    feedback = [
        _feedback(
            retrieval_id="r1", task_type="fix", verification_status=VerificationStatus.PASSED
        ),
        _feedback(
            retrieval_id="r2", task_type="doc_gen", verification_status=VerificationStatus.FAILED
        ),
    ]
    passport = rebuild_retrieval_passport(feedback, chunk_id="chunk-1")
    assert passport.task_type_buckets["fix"].verification.verified_success_count == 1
    assert passport.task_type_buckets["doc_gen"].verification.verification_failure_count == 1


def test_repository_bucket() -> None:
    feedback = [
        _feedback(retrieval_id="r1", repository_id="org/repo-a"),
        _feedback(retrieval_id="r2", repository_id="org/repo-b"),
    ]
    passport = rebuild_retrieval_passport(feedback, chunk_id="chunk-1")
    assert passport.repository_buckets["org/repo-a"].verification.verification_sample_count == 1
    assert passport.repository_buckets["org/repo-b"].verification.verification_sample_count == 1


def test_repository_task_type_bucket() -> None:
    feedback = [
        _feedback(retrieval_id="r1", repository_id="org/repo-a", task_type="fix"),
        _feedback(retrieval_id="r2", repository_id="org/repo-a", task_type="doc_gen"),
        _feedback(retrieval_id="r3", repository_id="org/repo-b", task_type="fix"),
    ]
    passport = rebuild_retrieval_passport(feedback, chunk_id="chunk-1")
    buckets = passport.repository_task_type_buckets
    assert buckets[("org/repo-a", "fix")].verification.verification_sample_count == 1
    assert buckets[("org/repo-a", "doc_gen")].verification.verification_sample_count == 1
    assert buckets[("org/repo-b", "fix")].verification.verification_sample_count == 1


def test_agent_bucket_when_agent_type_present() -> None:
    feedback = [
        _feedback(retrieval_id="r1", agent_type="claude-sonnet"),
        _feedback(retrieval_id="r2", agent_type="codex"),
    ]
    passport = rebuild_retrieval_passport(feedback, chunk_id="chunk-1")
    assert "claude-sonnet" in passport.agent_buckets
    assert "codex" in passport.agent_buckets
    assert passport.agent_buckets["claude-sonnet"].verification.verification_sample_count == 1


def test_no_task_or_repository_produces_no_bucket_entries() -> None:
    feedback = [_feedback(retrieval_id="r1", task_type=None, repository_id=None)]
    passport = rebuild_retrieval_passport(feedback, chunk_id="chunk-1")
    assert passport.task_type_buckets == {}
    assert passport.repository_buckets == {}
    assert passport.repository_task_type_buckets == {}
    assert passport.overall.verification.verification_sample_count == 1


# --- rebuildability -------------------------------------------------------------------------


def test_rebuild_all_retrieval_passports_groups_by_chunk() -> None:
    feedback = [
        _feedback(retrieval_id="r1", chunk_ids=("chunk-1",)),
        _feedback(retrieval_id="r2", chunk_ids=("chunk-2",)),
    ]
    passports = rebuild_all_retrieval_passports(feedback)
    assert set(passports.keys()) == {"chunk-1", "chunk-2"}


def test_rebuild_is_pure_and_repeatable() -> None:
    feedback = [
        _feedback(retrieval_id="r1", verification_status=VerificationStatus.PASSED),
        _feedback(retrieval_id="r2", verification_status=VerificationStatus.FAILED),
    ]
    p1 = rebuild_retrieval_passport(feedback, chunk_id="chunk-1")
    p2 = rebuild_retrieval_passport(feedback, chunk_id="chunk-1")
    assert p1 == p2


def test_shuffled_feedback_order_produces_identical_passport() -> None:
    feedback = [
        _feedback(
            retrieval_id=f"r{i}",
            verification_status=(
                VerificationStatus.PASSED if i % 2 == 0 else VerificationStatus.FAILED
            ),
            task_type="fix" if i % 3 else "doc_gen",
        )
        for i in range(12)
    ]
    shuffled = list(feedback)
    random.Random(11).shuffle(shuffled)

    forward = rebuild_retrieval_passport(feedback, chunk_id="chunk-1")
    from_shuffled = rebuild_retrieval_passport(shuffled, chunk_id="chunk-1")
    assert forward == from_shuffled


def test_rebuild_all_passports_order_independent() -> None:
    feedback = [_feedback(retrieval_id=f"r{i}", chunk_ids=(f"chunk-{i % 3}",)) for i in range(9)]
    shuffled = list(feedback)
    random.Random(5).shuffle(shuffled)

    forward = rebuild_all_retrieval_passports(feedback)
    from_shuffled = rebuild_all_retrieval_passports(shuffled)
    assert forward == from_shuffled


# --- stale content -------------------------------------------------------------------------


def test_stale_content_hash_excluded_from_passport() -> None:
    """Evidence recorded against old chunk content must not silently
    transfer to today's content when a current hash is supplied."""
    stale_feedback = _feedback(
        retrieval_id="r1", chunk_ids=("chunk-1",), chunk_content_hashes=("old-hash",)
    )
    fresh_feedback = _feedback(
        retrieval_id="r2", chunk_ids=("chunk-1",), chunk_content_hashes=("new-hash",)
    )
    passport = rebuild_retrieval_passport(
        [stale_feedback, fresh_feedback], chunk_id="chunk-1", current_content_hash="new-hash"
    )
    assert passport.overall.verification.verification_sample_count == 1


def test_no_current_hash_supplied_means_no_staleness_filtering() -> None:
    stale_feedback = _feedback(
        retrieval_id="r1", chunk_ids=("chunk-1",), chunk_content_hashes=("old-hash",)
    )
    passport = rebuild_retrieval_passport(
        [stale_feedback], chunk_id="chunk-1", current_content_hash=None
    )
    assert passport.overall.verification.verification_sample_count == 1


def test_feedback_without_recorded_hash_is_never_treated_as_stale() -> None:
    """Feedback that never recorded a content hash for this chunk (e.g.
    older data predating that field) is not penalized -- it simply has no
    staleness opinion."""
    no_hash_feedback = _feedback(retrieval_id="r1", chunk_ids=("chunk-1",))
    passport = rebuild_retrieval_passport(
        [no_hash_feedback], chunk_id="chunk-1", current_content_hash="new-hash"
    )
    assert passport.overall.verification.verification_sample_count == 1


def test_rebuild_all_passports_applies_per_chunk_current_hashes() -> None:
    feedback = [
        _feedback(retrieval_id="r1", chunk_ids=("chunk-1",), chunk_content_hashes=("old",)),
        _feedback(retrieval_id="r2", chunk_ids=("chunk-2",), chunk_content_hashes=("current-2",)),
    ]
    passports = rebuild_all_retrieval_passports(
        feedback, current_content_hashes={"chunk-1": "current-1", "chunk-2": "current-2"}
    )
    assert passports["chunk-1"].overall.verification.verification_sample_count == 0
    assert passports["chunk-2"].overall.verification.verification_sample_count == 1
