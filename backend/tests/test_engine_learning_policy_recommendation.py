"""Tests for `app.engine.learning.policy.LearningPolicy.recommend`: core
recommendation scenarios -- verified vs. execution success, low sample
size, no evidence, retries, cancellations, and missing latency/cost."""

from datetime import UTC, datetime

from app.contracts.enums import AgentExecutionStatus
from app.contracts.errors import FailureCategory
from app.contracts.passports import AgentPassportMetricBucket
from app.contracts.verification import VerificationStatus
from app.engine.learning.events import LearningEvent
from app.engine.learning.passport import rebuild_all_passports
from app.engine.learning.policy import LearningPolicy
from app.engine.learning.recommendation import LearningRecommendation, RecommendationOutcome
from app.engine.learning.scoring import execution_reliability

_NOW = datetime.now(UTC)


def _events(
    agent_type: str,
    n: int,
    *,
    prefix: str,
    execution_status: AgentExecutionStatus = AgentExecutionStatus.SUCCEEDED,
    verification_status: VerificationStatus | None = None,
    task_type: str | None = "code_generation",
    repository_id: str | None = None,
    duration_ms: float | None = None,
    attempt_number: int = 1,
    failure_category: FailureCategory | None = None,
) -> list[LearningEvent]:
    return [
        LearningEvent(
            event_id=f"{prefix}-{i}",
            workflow_id=f"wf-{prefix}-{i}",
            agent_type=agent_type,
            execution_status=execution_status,
            created_at=_NOW,
            task_type=task_type,
            repository_id=repository_id,
            duration_ms=duration_ms,
            verification_status=verification_status,
            attempt_number=attempt_number,
            failure_category=failure_category,
        )
        for i in range(n)
    ]


def _recommend(events: list[LearningEvent], **kwargs: object) -> LearningRecommendation:
    passports = rebuild_all_passports(events, updated_at=_NOW)
    return LearningPolicy().recommend(passports, **kwargs)  # type: ignore[arg-type]


# --- clear winner with sufficient verified evidence ---------------------------------------


def test_clear_winner_prefers_higher_verified_success_over_higher_execution_success() -> None:
    """The task's own example: Agent A has more execution successes but far
    worse verified success; Agent B has fewer execution successes but much
    better verified success. B must be preferred."""
    events = (
        _events("agent_a", 2, prefix="a-pass", verification_status=VerificationStatus.PASSED)
        + _events("agent_a", 8, prefix="a-fail", verification_status=VerificationStatus.FAILED)
        + _events("agent_b", 7, prefix="b-pass", verification_status=VerificationStatus.PASSED)
        + _events("agent_b", 1, prefix="b-fail", verification_status=VerificationStatus.FAILED)
    )
    rec = _recommend(events, task_type="code_generation")
    assert rec.recommended_agent_types == ("agent_b",)
    assert "agent_a" in rec.avoid_agent_types

    by_agent = {r.agent_type: r for r in rec.agent_recommendations}
    assert by_agent["agent_b"].score is not None
    assert by_agent["agent_a"].score is not None
    assert by_agent["agent_b"].score > by_agent["agent_a"].score


def test_multiple_similar_agents_ranked_by_score_descending() -> None:
    events = (
        _events("agent_a", 8, prefix="a", verification_status=VerificationStatus.PASSED)
        + _events("agent_b", 6, prefix="b", verification_status=VerificationStatus.PASSED)
        + _events("agent_b", 2, prefix="b2", verification_status=VerificationStatus.FAILED)
        + _events("agent_c", 5, prefix="c", verification_status=VerificationStatus.PASSED)
        + _events("agent_c", 3, prefix="c2", verification_status=VerificationStatus.FAILED)
    )
    rec = _recommend(events, task_type="code_generation")
    scores = [r.score for r in rec.agent_recommendations]
    assert all(score is not None for score in scores)
    non_none_scores = [score for score in scores if score is not None]
    assert non_none_scores == sorted(non_none_scores, reverse=True)
    assert rec.agent_recommendations[0].agent_type == "agent_a"


# --- low sample size / no evidence --------------------------------------------------------


def test_low_sample_size_yields_insufficient_evidence() -> None:
    events = _events("agent_a", 2, prefix="a", verification_status=VerificationStatus.PASSED)
    rec = _recommend(events, task_type="code_generation")
    agent_a = rec.agent_recommendations[0]
    assert agent_a.outcome is RecommendationOutcome.INSUFFICIENT_EVIDENCE
    assert agent_a.score is None
    assert "agent_a" in rec.insufficient_evidence_agent_types


def test_no_evidence_for_unknown_candidate() -> None:
    events = _events("agent_a", 8, prefix="a", verification_status=VerificationStatus.PASSED)
    rec = _recommend(
        events, task_type="code_generation", candidate_agent_types=["agent_a", "agent_never_seen"]
    )
    by_agent = {r.agent_type: r for r in rec.agent_recommendations}
    assert by_agent["agent_never_seen"].outcome is RecommendationOutcome.NO_EVIDENCE
    assert by_agent["agent_never_seen"].score is None
    assert "agent_never_seen" in rec.insufficient_evidence_agent_types


def test_no_evidence_when_passport_has_zero_executions() -> None:
    rec = _recommend([], task_type="code_generation", candidate_agent_types=["agent_a"])
    assert rec.agent_recommendations[0].outcome is RecommendationOutcome.NO_EVIDENCE


# --- verification failures / execution vs verified success ---------------------------------


def test_verification_failures_trigger_reason_code_and_reduce_score() -> None:
    good_events = _events(
        "agent_good", 8, prefix="good", verification_status=VerificationStatus.PASSED
    )
    bad_events = _events(
        "agent_bad", 5, prefix="bad-pass", verification_status=VerificationStatus.PASSED
    ) + _events("agent_bad", 5, prefix="bad-fail", verification_status=VerificationStatus.FAILED)
    rec = _recommend(good_events + bad_events, task_type="code_generation")
    by_agent = {r.agent_type: r for r in rec.agent_recommendations}
    assert "verification_failure_history" in by_agent["agent_bad"].reason_codes
    good_score, bad_score = by_agent["agent_good"].score, by_agent["agent_bad"].score
    assert good_score is not None and bad_score is not None
    assert good_score > bad_score


def test_execution_success_but_verification_failure_is_not_verified_success() -> None:
    """A single event: the execution itself succeeded, but Stage 4E
    verification failed -- must never be counted as verified success."""
    events = _events(
        "agent_a",
        6,
        prefix="a",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        verification_status=VerificationStatus.FAILED,
    )
    rec = _recommend(events, task_type="code_generation")
    agent_a = rec.agent_recommendations[0]
    assert agent_a.verified_success_rate == 0.0
    assert agent_a.outcome is RecommendationOutcome.AVOID_IF_POSSIBLE


def test_verified_success_drives_recommend_outcome() -> None:
    events = _events("agent_a", 9, prefix="a", verification_status=VerificationStatus.PASSED)
    rec = _recommend(events, task_type="code_generation")
    agent_a = rec.agent_recommendations[0]
    assert agent_a.verified_success_rate == 1.0
    assert agent_a.outcome is RecommendationOutcome.RECOMMEND


# --- retries ---------------------------------------------------------------------------------


def test_high_retry_rate_triggers_reason_code_and_reduces_score() -> None:
    low_retry = _events(
        "agent_low_retry",
        8,
        prefix="lr",
        verification_status=VerificationStatus.PASSED,
        attempt_number=1,
    )
    high_retry = _events(
        "agent_high_retry",
        3,
        prefix="hr1",
        verification_status=VerificationStatus.PASSED,
        attempt_number=1,
    ) + _events(
        "agent_high_retry",
        5,
        prefix="hr2",
        verification_status=VerificationStatus.PASSED,
        attempt_number=2,
    )
    rec = _recommend(low_retry + high_retry, task_type="code_generation")
    by_agent = {r.agent_type: r for r in rec.agent_recommendations}
    assert "retry_history" in by_agent["agent_high_retry"].reason_codes
    assert "retry_history" not in by_agent["agent_low_retry"].reason_codes
    low_retry_score = by_agent["agent_low_retry"].score
    high_retry_score = by_agent["agent_high_retry"].score
    assert low_retry_score is not None and high_retry_score is not None
    assert low_retry_score > high_retry_score


# --- cancellations: must remain neutral -------------------------------------------------------


def test_cancellation_does_not_affect_execution_reliability_component() -> None:
    without_cancellation = AgentPassportMetricBucket(
        execution_count=10, success_count=8, failure_count=2
    )
    with_cancellation = AgentPassportMetricBucket(
        execution_count=15, success_count=8, failure_count=2
    )
    assert execution_reliability(without_cancellation) == execution_reliability(with_cancellation)


def test_cancellations_do_not_worsen_recommendation_outcome() -> None:
    base_events = _events(
        "agent_a", 8, prefix="a", verification_status=VerificationStatus.PASSED
    )
    cancelled_events = _events(
        "agent_a",
        4,
        prefix="c",
        execution_status=AgentExecutionStatus.CANCELLED,
        failure_category=FailureCategory.CANCELLED,
    )
    without = _recommend(base_events, task_type="code_generation")
    with_cancellations = _recommend(base_events + cancelled_events, task_type="code_generation")
    without_result = without.agent_recommendations[0]
    with_cancellations_result = with_cancellations.agent_recommendations[0]
    assert without_result.outcome == with_cancellations_result.outcome
    assert without_result.score == with_cancellations_result.score


# --- missing latency / missing cost -----------------------------------------------------------


def test_missing_latency_evidence_does_not_crash_and_uses_neutral_component() -> None:
    events = _events(
        "agent_a", 8, prefix="a", verification_status=VerificationStatus.PASSED, duration_ms=None
    )
    rec = _recommend(events, task_type="code_generation")
    assert rec.agent_recommendations[0].outcome is RecommendationOutcome.RECOMMEND


def test_missing_cost_evidence_never_affects_recommendation() -> None:
    """Cost is not a Stage 5B scoring input at all (see scoring.py) -- a
    passport with real cost evidence and one without must recommend
    identically, all else equal."""
    events_no_cost = _events(
        "agent_a", 8, prefix="a", verification_status=VerificationStatus.PASSED
    )
    events_with_cost = [
        LearningEvent(
            event_id=e.event_id,
            workflow_id=e.workflow_id,
            agent_type=e.agent_type,
            execution_status=e.execution_status,
            created_at=e.created_at,
            task_type=e.task_type,
            verification_status=e.verification_status,
            cost_usd=0.05,
        )
        for e in events_no_cost
    ]
    rec_no_cost = _recommend(events_no_cost, task_type="code_generation")
    rec_with_cost = _recommend(events_with_cost, task_type="code_generation")
    no_cost_score = rec_no_cost.agent_recommendations[0].score
    with_cost_score = rec_with_cost.agent_recommendations[0].score
    assert no_cost_score == with_cost_score
