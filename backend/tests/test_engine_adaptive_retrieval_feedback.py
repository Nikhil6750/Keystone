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
    fb = _feedback(evidence_source=EvidenceSource.BENCHMARK, campaign_id="campaign-42")
    assert fb.evidence_source is EvidenceSource.BENCHMARK
    assert fb.campaign_id == "campaign-42"


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
