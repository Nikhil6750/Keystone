"""Tests for `app.engine.adaptive_retrieval.feedback`: `RetrievalFeedback`
verified-success semantics, benchmark/production provenance, deterministic
identity, and the in-memory repository."""

from datetime import UTC, datetime

import pytest

from app.contracts.enums import AgentExecutionStatus
from app.contracts.verification import VerificationStatus
from app.engine.adaptive_retrieval.errors import (
    MalformedRetrievalFeedbackError,
    RetrievalFeedbackConflictError,
)
from app.engine.adaptive_retrieval.feedback import (
    InMemoryRetrievalFeedbackRepository,
    RetrievalFeedback,
)
from app.engine.benchmark_learning.models import EvidenceSource

_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _feedback(**overrides) -> RetrievalFeedback:
    defaults = dict(
        retrieval_id="retrieval::fp1::fix::org/repo::c1,c2",
        chunk_ids=("c1", "c2"),
        verification_status=VerificationStatus.PASSED,
        task_type="fix",
        repository_id="org/repo",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        execution_id="execution-1",
        created_at=_CREATED_AT,
    )
    defaults.update(overrides)
    return RetrievalFeedback(**defaults)


# --- construction / validation --------------------------------------------------------------


def test_valid_feedback_constructs() -> None:
    fb = _feedback()
    assert fb.chunk_ids == ("c1", "c2")
    assert fb.evidence_source is EvidenceSource.PRODUCTION


def test_blank_retrieval_id_rejected() -> None:
    with pytest.raises(MalformedRetrievalFeedbackError, match="retrieval_id"):
        _feedback(retrieval_id="   ")


def test_empty_chunk_ids_rejected() -> None:
    with pytest.raises(MalformedRetrievalFeedbackError, match="chunk_ids"):
        _feedback(chunk_ids=())


def test_duplicate_chunk_ids_rejected() -> None:
    with pytest.raises(MalformedRetrievalFeedbackError, match="duplicates"):
        _feedback(chunk_ids=("c1", "c1"))


def test_mismatched_content_hash_length_rejected() -> None:
    with pytest.raises(MalformedRetrievalFeedbackError, match="chunk_content_hashes"):
        _feedback(chunk_ids=("c1", "c2"), chunk_content_hashes=("h1",))


# --- verified-success semantics (non-negotiable) -----------------------------------------------


def test_passed_is_verified_success() -> None:
    fb = _feedback(verification_status=VerificationStatus.PASSED)
    assert fb.is_verified_success is True
    assert fb.is_verified_failure is False


def test_failed_is_verified_failure_not_success() -> None:
    fb = _feedback(verification_status=VerificationStatus.FAILED)
    assert fb.is_verified_success is False
    assert fb.is_verified_failure is True


def test_inconclusive_is_neither_success_nor_failure() -> None:
    fb = _feedback(verification_status=VerificationStatus.INCONCLUSIVE)
    assert fb.is_verified_success is False
    assert fb.is_verified_failure is False


def test_requires_human_review_is_never_verified_success() -> None:
    fb = _feedback(verification_status=VerificationStatus.REQUIRES_HUMAN_REVIEW)
    assert fb.is_verified_success is False
    assert fb.is_verified_failure is False


def test_execution_succeeded_with_verification_failed_is_not_success() -> None:
    """The non-negotiable rule: execution success alone must never count as
    retrieval success. Only verification_status feeds is_verified_success --
    execution_status participates in neither property."""
    fb = _feedback(
        execution_status=AgentExecutionStatus.SUCCEEDED,
        verification_status=VerificationStatus.FAILED,
    )
    assert fb.is_verified_success is False


def test_execution_failed_with_no_verification_run_is_not_success() -> None:
    fb = _feedback(
        execution_status=AgentExecutionStatus.FAILED,
        verification_status=VerificationStatus.INCONCLUSIVE,
    )
    assert fb.is_verified_success is False


# --- provenance: benchmark vs production ------------------------------------------------------


def test_production_evidence_forbids_campaign_id() -> None:
    with pytest.raises(MalformedRetrievalFeedbackError, match="campaign_id must be None"):
        _feedback(evidence_source=EvidenceSource.PRODUCTION, campaign_id="camp-1")


def test_benchmark_evidence_requires_campaign_id() -> None:
    with pytest.raises(MalformedRetrievalFeedbackError, match="campaign_id is required"):
        _feedback(evidence_source=EvidenceSource.BENCHMARK, campaign_id=None)


def test_benchmark_evidence_requires_non_blank_campaign_id() -> None:
    with pytest.raises(MalformedRetrievalFeedbackError, match="campaign_id is required"):
        _feedback(evidence_source=EvidenceSource.BENCHMARK, campaign_id="   ")


def test_valid_benchmark_feedback_with_campaign_id() -> None:
    fb = _feedback(
        evidence_source=EvidenceSource.BENCHMARK, campaign_id="campaign-42", execution_id=None
    )
    assert fb.evidence_source is EvidenceSource.BENCHMARK
    assert fb.campaign_id == "campaign-42"
    assert fb.execution_id is None


# --- content_hash_for -----------------------------------------------------------------------


def test_content_hash_for_present() -> None:
    fb = _feedback(chunk_ids=("c1", "c2"), chunk_content_hashes=("h1", "h2"))
    assert fb.content_hash_for("c2") == "h2"


def test_content_hash_for_absent_when_not_provided() -> None:
    fb = _feedback(chunk_ids=("c1", "c2"))
    assert fb.content_hash_for("c1") is None


# --- identity -----------------------------------------------------------------------------------


def test_feedback_id_deterministic() -> None:
    fb1 = _feedback()
    fb2 = _feedback()
    assert fb1.feedback_id == fb2.feedback_id


def test_feedback_id_not_affected_by_created_at() -> None:
    fb1 = _feedback(created_at=datetime(2020, 1, 1, tzinfo=UTC))
    fb2 = _feedback(created_at=datetime(2099, 12, 31, tzinfo=UTC))
    assert fb1.feedback_id == fb2.feedback_id


def test_feedback_id_differs_by_verification_status() -> None:
    fb1 = _feedback(verification_status=VerificationStatus.PASSED)
    fb2 = _feedback(verification_status=VerificationStatus.FAILED)
    assert fb1.feedback_id != fb2.feedback_id


def test_feedback_id_differs_by_retrieval_id() -> None:
    fb1 = _feedback(retrieval_id="retrieval::a")
    fb2 = _feedback(retrieval_id="retrieval::b")
    assert fb1.feedback_id != fb2.feedback_id


# --- execution identity (Stage 7.5 hardening) ------------------------------------------------


def test_blank_production_execution_id_rejected() -> None:
    with pytest.raises(MalformedRetrievalFeedbackError, match="execution_id"):
        _feedback(execution_id="   ")


def test_missing_production_execution_id_rejected() -> None:
    with pytest.raises(MalformedRetrievalFeedbackError, match="execution_id"):
        _feedback(execution_id=None)


def test_same_production_execution_reprocessed_yields_same_feedback_id() -> None:
    """Reprocessing execution A (identical retrieval_id, execution_id, and
    observable outcome) must be idempotent."""
    fb1 = _feedback(execution_id="execution-A")
    fb2 = _feedback(execution_id="execution-A")
    assert fb1.feedback_id == fb2.feedback_id


def test_different_execution_id_same_retrieval_and_outcome_yields_different_feedback_id() -> None:
    """Two independent production executions (A and B) that happen to reuse
    the same retrieval configuration and reach the same verified outcome
    must still be two distinct feedback identities."""
    fb_a = _feedback(execution_id="execution-A")
    fb_b = _feedback(execution_id="execution-B")
    assert fb_a.retrieval_id == fb_b.retrieval_id  # same semantic retrieval
    assert fb_a.verification_status == fb_b.verification_status  # same outcome
    assert fb_a.feedback_id != fb_b.feedback_id  # but different executions


def test_execution_id_not_affected_by_created_at() -> None:
    fb1 = _feedback(execution_id="execution-A", created_at=datetime(2020, 1, 1, tzinfo=UTC))
    fb2 = _feedback(execution_id="execution-A", created_at=datetime(2099, 12, 31, tzinfo=UTC))
    assert fb1.feedback_id == fb2.feedback_id


def test_benchmark_feedback_id_still_uses_campaign_id_not_execution_id() -> None:
    """Benchmark feedback_id computation is unchanged by this fix: it keys
    on campaign_id, and execution_id (forbidden for benchmark) never enters
    the formula."""
    fb1 = _feedback(
        evidence_source=EvidenceSource.BENCHMARK, campaign_id="campaign-1", execution_id=None
    )
    fb2 = _feedback(
        evidence_source=EvidenceSource.BENCHMARK, campaign_id="campaign-1", execution_id=None
    )
    fb_other_campaign = _feedback(
        evidence_source=EvidenceSource.BENCHMARK, campaign_id="campaign-2", execution_id=None
    )
    assert fb1.feedback_id == fb2.feedback_id  # same campaign -> same identity
    assert fb1.feedback_id != fb_other_campaign.feedback_id  # different campaign -> different


def test_benchmark_feedback_id_matches_pre_hardening_format() -> None:
    """Golden-value regression: benchmark feedback_id must be byte-identical
    to the formula used before this fix (campaign_id in the discriminator
    slot, execution_id never present)."""
    fb = _feedback(
        retrieval_id="retrieval::fp1::fix::org/repo::c1,c2",
        verification_status=VerificationStatus.PASSED,
        evidence_source=EvidenceSource.BENCHMARK,
        campaign_id="campaign-1",
        execution_id=None,
    )
    expected = (
        "feedback::retrieval::fp1::fix::org/repo::c1,c2::passed::succeeded::benchmark::"
        "campaign-1"
    )
    assert fb.feedback_id == expected


# --- repository -----------------------------------------------------------------------------


def test_repository_stores_and_retrieves() -> None:
    repo = InMemoryRetrievalFeedbackRepository()
    fb = _feedback()
    repo.add(fb)
    assert repo.all() == [fb]


def test_repository_idempotent_for_identical_readd() -> None:
    repo = InMemoryRetrievalFeedbackRepository()
    fb = _feedback()
    repo.add(fb)
    repo.add(fb)
    assert len(repo.all()) == 1


def test_repository_rejects_conflicting_readd() -> None:
    repo = InMemoryRetrievalFeedbackRepository()
    fb_passed = _feedback(verification_status=VerificationStatus.PASSED)
    fb_failed = RetrievalFeedback(
        retrieval_id=fb_passed.retrieval_id,  # same retrieval_id
        chunk_ids=fb_passed.chunk_ids,
        verification_status=VerificationStatus.PASSED,  # same status too
        task_type="doc_gen",  # but different task_type -> different content, same feedback_id
        repository_id="org/repo",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        execution_id=fb_passed.execution_id,  # same execution_id too -> same feedback_id
    )
    repo.add(fb_passed)
    with pytest.raises(RetrievalFeedbackConflictError):
        repo.add(fb_failed)


def test_repository_returns_stable_deterministic_order() -> None:
    repo = InMemoryRetrievalFeedbackRepository()
    fb_a = _feedback(retrieval_id="retrieval::z")
    fb_b = _feedback(retrieval_id="retrieval::a")
    repo.add(fb_a)
    repo.add(fb_b)
    ids = [fb.feedback_id for fb in repo.all()]
    assert ids == sorted(ids)


def test_repository_constructor_accepts_initial_feedback() -> None:
    fb = _feedback()
    repo = InMemoryRetrievalFeedbackRepository([fb])
    assert repo.all() == [fb]
