"""Tests for `app.engine.adaptive_retrieval.policy.AdaptiveRetrievalPolicy`:
conservative defaults, validation, and benchmark/production evidence
separation (never blended)."""

from datetime import UTC, datetime

import pytest

from app.contracts.enums import AgentExecutionStatus
from app.contracts.verification import VerificationStatus
from app.engine.adaptive_retrieval.errors import MalformedAdaptiveRetrievalPolicyError
from app.engine.adaptive_retrieval.feedback import RetrievalFeedback
from app.engine.adaptive_retrieval.policy import AdaptiveRetrievalPolicy
from app.engine.benchmark_learning.models import EvidenceSource
from app.engine.learning.aggregation import MIN_SAMPLE_SIZE_FOR_CONFIDENCE

_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _feedback(
    *, retrieval_id: str, evidence_source: EvidenceSource, campaign_id: str | None = None
) -> RetrievalFeedback:
    is_production = evidence_source is EvidenceSource.PRODUCTION
    return RetrievalFeedback(
        retrieval_id=retrieval_id,
        chunk_ids=("chunk-1",),
        verification_status=VerificationStatus.PASSED,
        task_type="fix",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        evidence_source=evidence_source,
        campaign_id=campaign_id,
        execution_id=f"execution-for-{retrieval_id}" if is_production else None,
        created_at=_CREATED_AT,
    )


# --- defaults / validation --------------------------------------------------------------------


def test_default_policy_is_disabled() -> None:
    policy = AdaptiveRetrievalPolicy()
    assert policy.enabled is False


def test_default_minimum_samples_matches_stage5_constant() -> None:
    policy = AdaptiveRetrievalPolicy()
    assert policy.minimum_verified_samples == MIN_SAMPLE_SIZE_FOR_CONFIDENCE


def test_default_benchmark_evidence_disallowed() -> None:
    policy = AdaptiveRetrievalPolicy()
    assert policy.allow_benchmark_evidence is False


def test_default_production_evidence_allowed() -> None:
    policy = AdaptiveRetrievalPolicy()
    assert policy.allow_production_evidence is True


def test_negative_minimum_samples_rejected() -> None:
    with pytest.raises(MalformedAdaptiveRetrievalPolicyError, match="minimum_verified_samples"):
        AdaptiveRetrievalPolicy(minimum_verified_samples=0)


def test_negative_positive_adjustment_rejected() -> None:
    with pytest.raises(MalformedAdaptiveRetrievalPolicyError, match="max_positive_adjustment"):
        AdaptiveRetrievalPolicy(max_positive_adjustment=-0.1)


def test_negative_negative_adjustment_rejected() -> None:
    with pytest.raises(MalformedAdaptiveRetrievalPolicyError, match="max_negative_adjustment"):
        AdaptiveRetrievalPolicy(max_negative_adjustment=-0.1)


def test_disallowing_both_evidence_sources_rejected() -> None:
    with pytest.raises(MalformedAdaptiveRetrievalPolicyError):
        AdaptiveRetrievalPolicy(allow_production_evidence=False, allow_benchmark_evidence=False)


# --- evidence separation: never blended -------------------------------------------------------


def test_production_feedback_returns_only_production_by_default() -> None:
    policy = AdaptiveRetrievalPolicy(enabled=True)
    feedback = [
        _feedback(retrieval_id="r1", evidence_source=EvidenceSource.PRODUCTION),
        _feedback(retrieval_id="r2", evidence_source=EvidenceSource.BENCHMARK, campaign_id="c1"),
    ]
    result = policy.production_feedback(feedback)
    assert len(result) == 1
    assert result[0].evidence_source is EvidenceSource.PRODUCTION


def test_benchmark_feedback_empty_by_default() -> None:
    """`allow_benchmark_evidence` defaults to False, so benchmark_feedback
    returns nothing even when benchmark records are present."""
    policy = AdaptiveRetrievalPolicy(enabled=True)
    feedback = [
        _feedback(retrieval_id="r2", evidence_source=EvidenceSource.BENCHMARK, campaign_id="c1"),
    ]
    assert policy.benchmark_feedback(feedback) == []


def test_benchmark_feedback_returned_when_explicitly_allowed() -> None:
    policy = AdaptiveRetrievalPolicy(enabled=True, allow_benchmark_evidence=True)
    feedback = [
        _feedback(retrieval_id="r1", evidence_source=EvidenceSource.PRODUCTION),
        _feedback(retrieval_id="r2", evidence_source=EvidenceSource.BENCHMARK, campaign_id="c1"),
    ]
    result = policy.benchmark_feedback(feedback)
    assert len(result) == 1
    assert result[0].evidence_source is EvidenceSource.BENCHMARK


def test_production_feedback_empty_when_disallowed() -> None:
    policy = AdaptiveRetrievalPolicy(
        enabled=True, allow_production_evidence=False, allow_benchmark_evidence=True
    )
    feedback = [_feedback(retrieval_id="r1", evidence_source=EvidenceSource.PRODUCTION)]
    assert policy.production_feedback(feedback) == []


def test_production_and_benchmark_feedback_are_always_disjoint() -> None:
    """The two source-scoped lists never overlap -- a caller cannot
    accidentally build one blended passport from a single combined list,
    because no such combined list is ever returned by this API."""
    policy = AdaptiveRetrievalPolicy(enabled=True, allow_benchmark_evidence=True)
    production = _feedback(retrieval_id="r1", evidence_source=EvidenceSource.PRODUCTION)
    benchmark = _feedback(
        retrieval_id="r2", evidence_source=EvidenceSource.BENCHMARK, campaign_id="c1"
    )
    mixed = [production, benchmark]
    production_only = policy.production_feedback(mixed)
    benchmark_only = policy.benchmark_feedback(mixed)
    assert production_only == [production]
    assert benchmark_only == [benchmark]
    assert set(production_only).isdisjoint(set(benchmark_only))
