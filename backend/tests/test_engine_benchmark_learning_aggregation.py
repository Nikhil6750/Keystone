"""Stage 7B AGGREGATION + RECOMMENDATION tests: benchmark-derived
`LearningEvent`s flow through Stage 5A's existing, unmodified aggregation
and Stage 5B's existing, unmodified recommendation policy correctly."""

from datetime import UTC, datetime

from app.contracts.enums import AgentExecutionStatus, BenchmarkEvaluatorType
from app.contracts.errors import FailureCategory
from app.contracts.verification import VerificationResult, VerificationStatus
from app.engine.benchmark.models import BenchmarkExecutionResult
from app.engine.benchmark_learning.adapter import (
    build_benchmark_learning_passports,
    convert_benchmark_results_to_learning_records,
)
from app.engine.benchmark_learning.policy import BenchmarkLearningPolicy
from app.engine.learning.policy import LearningPolicy
from app.engine.learning.recommendation import RecommendationOutcome

_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)
_CAMPAIGN_ID = "campaign-1"


def _verification_result(status: VerificationStatus) -> VerificationResult:
    return VerificationResult(
        verification_id="ver-1",
        workflow_id="bm-s1",
        step_id="c1",
        status=status,
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        failure_reason="mismatch" if status is VerificationStatus.FAILED else None,
        created_at=_CREATED_AT,
    )


def _result(
    *,
    case_id: str = "c1",
    repetition: int = 1,
    execution_status: AgentExecutionStatus = AgentExecutionStatus.SUCCEEDED,
    verification_status: VerificationStatus = VerificationStatus.PASSED,
    failure_category: FailureCategory | None = None,
    duration_ms: float = 100.0,
    agent_type: str = "a1",
) -> BenchmarkExecutionResult:
    return BenchmarkExecutionResult(
        suite_id="s1",
        case_id=case_id,
        agent_type=agent_type,
        repetition=repetition,
        task_type="fix",
        execution_status=execution_status,
        verification_status=verification_status,
        verification_result=_verification_result(verification_status),
        duration_ms=duration_ms,
        failure_category=failure_category,
        created_at=_CREATED_AT,
    )


def _passports_for(results: list[BenchmarkExecutionResult]) -> dict:
    records = convert_benchmark_results_to_learning_records(results, campaign_id=_CAMPAIGN_ID)
    filtered = BenchmarkLearningPolicy(enabled=True).filter_records(records)
    return build_benchmark_learning_passports(filtered, updated_at=_CREATED_AT)


# --- AGGREGATION --------------------------------------------------------------------------


def test_aggregation_verified_success_only_counts_passed() -> None:
    results = [
        _result(repetition=1, verification_status=VerificationStatus.PASSED),
        _result(repetition=2, verification_status=VerificationStatus.FAILED),
        _result(repetition=3, verification_status=VerificationStatus.INCONCLUSIVE),
        _result(repetition=4, verification_status=VerificationStatus.REQUIRES_HUMAN_REVIEW),
    ]
    passports = _passports_for(results)
    verification = passports["a1"].overall_verification
    assert verification.verified_success_count == 1
    assert verification.verification_failure_count == 1
    assert verification.verification_inconclusive_count == 1
    assert verification.human_review_count == 1
    assert verification.verification_sample_count == 4
    assert verification.verified_success_rate == 0.25


def test_aggregation_execution_success_separate_from_verification_failure() -> None:
    results = [
        _result(
            execution_status=AgentExecutionStatus.SUCCEEDED,
            verification_status=VerificationStatus.FAILED,
        )
    ]
    passports = _passports_for(results)
    p = passports["a1"]
    assert p.overall_metrics.success_count == 1  # execution succeeded
    assert p.overall_verification.verified_success_count == 0  # but not verified
    assert p.overall_verification.verification_failure_count == 1


def test_aggregation_cancellation_semantics_match_stage5() -> None:
    results = [
        _result(
            repetition=1,
            execution_status=AgentExecutionStatus.CANCELLED,
            verification_status=VerificationStatus.INCONCLUSIVE,
            failure_category=FailureCategory.CANCELLED,
        ),
        _result(
            repetition=2,
            execution_status=AgentExecutionStatus.SUCCEEDED,
            verification_status=VerificationStatus.PASSED,
        ),
    ]
    passports = _passports_for(results)
    m = passports["a1"].overall_metrics
    # Stage 5A rule: CANCELLED counts in execution_count but neither
    # success_count nor failure_count.
    assert m.execution_count == 2
    assert m.success_count == 1
    assert m.failure_count == 0


def test_aggregation_timeout_counts_as_execution_failure() -> None:
    results = [
        _result(
            execution_status=AgentExecutionStatus.TIMED_OUT,
            verification_status=VerificationStatus.INCONCLUSIVE,
            failure_category=FailureCategory.TIMEOUT,
        ),
    ]
    passports = _passports_for(results)
    m = passports["a1"].overall_metrics
    assert m.execution_count == 1
    assert m.failure_count == 1
    assert m.success_count == 0


def test_aggregation_no_duplicated_formula_reused_from_stage5() -> None:
    """Sanity check that benchmark-derived passports use real Stage 5A
    percentile/median computation (not some parallel implementation) by
    cross-checking against directly-built LearningEvents through the same
    Stage 5A entrypoint."""
    from app.engine.learning.passport import rebuild_all_passports

    results = [_result(repetition=i, duration_ms=float(100 * i)) for i in range(1, 6)]
    records = convert_benchmark_results_to_learning_records(results, campaign_id=_CAMPAIGN_ID)
    via_adapter = build_benchmark_learning_passports(records, updated_at=_CREATED_AT)
    via_direct_stage5 = rebuild_all_passports([r.event for r in records], updated_at=_CREATED_AT)
    assert via_adapter["a1"] == via_direct_stage5["a1"]


# --- RECOMMENDATION -------------------------------------------------------------------------


def test_recommendation_engine_accepts_benchmark_derived_passports() -> None:
    results = [
        _result(repetition=i, verification_status=VerificationStatus.PASSED) for i in range(1, 7)
    ]
    passports = _passports_for(results)
    recommendation = LearningPolicy().recommend(passports, task_type="fix")
    assert len(recommendation.agent_recommendations) == 1
    rec = recommendation.agent_recommendations[0]
    assert rec.agent_type == "a1"
    assert rec.outcome is RecommendationOutcome.RECOMMEND
    assert rec.verified_success_rate == 1.0


def test_recommendation_is_deterministic() -> None:
    results = [
        _result(repetition=i, agent_type="agent-a", verification_status=VerificationStatus.PASSED)
        for i in range(1, 7)
    ] + [
        _result(repetition=i, agent_type="agent-b", verification_status=VerificationStatus.FAILED)
        for i in range(1, 7)
    ]
    passports = _passports_for(results)

    first = LearningPolicy().recommend(passports, task_type="fix")
    for _ in range(5):
        again = LearningPolicy().recommend(passports, task_type="fix")
        assert again == first
