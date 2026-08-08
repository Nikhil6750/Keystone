"""Stage 7B MAPPING + FIELDS tests: `BenchmarkExecutionResult` ->
`LearningEvent` field-by-field correctness, across every execution/
verification status combination."""

from datetime import UTC, datetime

import pytest

from app.contracts.enums import AgentExecutionStatus, BenchmarkEvaluatorType
from app.contracts.errors import FailureCategory
from app.contracts.verification import VerificationResult, VerificationStatus
from app.engine.benchmark.models import BenchmarkExecutionResult
from app.engine.benchmark_learning.adapter import convert_benchmark_result_to_learning_event
from app.engine.benchmark_learning.errors import MalformedBenchmarkLearningInputError
from app.engine.benchmark_learning.models import EvidenceSource

_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)
_CAMPAIGN_ID = "campaign-1"


def _convert(result: BenchmarkExecutionResult, *, created_at: datetime | None = None):
    return convert_benchmark_result_to_learning_event(
        result, campaign_id=_CAMPAIGN_ID, created_at=created_at
    )


def _verification_result(
    status: VerificationStatus, *, failure_reason: str | None = None
) -> VerificationResult:
    return VerificationResult(
        verification_id="ver-1",
        workflow_id="bm-s1",
        step_id="c1",
        status=status,
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        failure_reason=failure_reason,
        created_at=_CREATED_AT,
    )


def _result(
    *,
    suite_id: str = "s1",
    case_id: str = "c1",
    agent_type: str = "a1",
    repetition: int = 1,
    task_type: str = "fix",
    execution_status: AgentExecutionStatus = AgentExecutionStatus.SUCCEEDED,
    verification_status: VerificationStatus = VerificationStatus.PASSED,
    duration_ms: float = 100.0,
    repository_id: str | None = None,
    failure_category: FailureCategory | None = None,
    cost_usd: float | None = None,
    created_at: datetime | None = _CREATED_AT,
) -> BenchmarkExecutionResult:
    failure_reason = "mismatch" if verification_status is VerificationStatus.FAILED else None
    return BenchmarkExecutionResult(
        suite_id=suite_id,
        case_id=case_id,
        agent_type=agent_type,
        repetition=repetition,
        task_type=task_type,
        execution_status=execution_status,
        verification_status=verification_status,
        verification_result=_verification_result(
            verification_status, failure_reason=failure_reason
        ),
        duration_ms=duration_ms,
        repository_id=repository_id,
        failure_category=failure_category,
        cost_usd=cost_usd,
        created_at=created_at,
    )


# --- MAPPING: verification status ---------------------------------------------------------


def test_mapping_passed_verification() -> None:
    record = _convert(_result(verification_status=VerificationStatus.PASSED))
    assert record.event.verification_status is VerificationStatus.PASSED
    assert record.event.execution_status is AgentExecutionStatus.SUCCEEDED


def test_mapping_failed_verification() -> None:
    record = _convert(_result(verification_status=VerificationStatus.FAILED))
    assert record.event.verification_status is VerificationStatus.FAILED
    assert record.event.execution_status is AgentExecutionStatus.SUCCEEDED


def test_mapping_inconclusive_verification() -> None:
    record = _convert(_result(verification_status=VerificationStatus.INCONCLUSIVE))
    assert record.event.verification_status is VerificationStatus.INCONCLUSIVE


def test_mapping_requires_human_review_verification() -> None:
    record = _convert(_result(verification_status=VerificationStatus.REQUIRES_HUMAN_REVIEW))
    assert record.event.verification_status is VerificationStatus.REQUIRES_HUMAN_REVIEW


# --- MAPPING: execution status --------------------------------------------------------------


def test_mapping_failed_execution() -> None:
    result = _result(
        execution_status=AgentExecutionStatus.FAILED,
        verification_status=VerificationStatus.INCONCLUSIVE,
        failure_category=FailureCategory.INTERNAL_ERROR,
    )
    record = _convert(result)
    assert record.event.execution_status is AgentExecutionStatus.FAILED
    assert record.event.failure_category is FailureCategory.INTERNAL_ERROR
    assert record.provenance.execution_status is AgentExecutionStatus.FAILED


def test_mapping_timed_out_execution() -> None:
    result = _result(
        execution_status=AgentExecutionStatus.TIMED_OUT,
        verification_status=VerificationStatus.INCONCLUSIVE,
        failure_category=FailureCategory.TIMEOUT,
    )
    record = _convert(result)
    assert record.event.execution_status is AgentExecutionStatus.TIMED_OUT
    assert record.event.failure_category is FailureCategory.TIMEOUT


def test_mapping_cancelled_execution() -> None:
    result = _result(
        execution_status=AgentExecutionStatus.CANCELLED,
        verification_status=VerificationStatus.INCONCLUSIVE,
        failure_category=FailureCategory.CANCELLED,
    )
    record = _convert(result)
    assert record.event.execution_status is AgentExecutionStatus.CANCELLED
    assert record.event.failure_category is FailureCategory.CANCELLED


# --- provenance source --------------------------------------------------------------------


def test_provenance_source_is_always_benchmark() -> None:
    record = _convert(_result())
    assert record.provenance.source is EvidenceSource.BENCHMARK


def test_provenance_carries_full_identity() -> None:
    result = _result(suite_id="suite-x", case_id="case-y", agent_type="agent-z", repetition=4)
    record = _convert(result)
    assert record.provenance.campaign_id == _CAMPAIGN_ID
    assert record.provenance.suite_id == "suite-x"
    assert record.provenance.case_id == "case-y"
    assert record.provenance.agent_type == "agent-z"
    assert record.provenance.repetition == 4


# --- FIELDS ---------------------------------------------------------------------------------


def test_field_task_type_preserved() -> None:
    record = _convert(_result(task_type="code_review"))
    assert record.event.task_type == "code_review"


def test_field_repository_id_preserved_when_present() -> None:
    record = _convert(_result(repository_id="org/repo"))
    assert record.event.repository_id == "org/repo"


def test_field_repository_id_none_when_absent() -> None:
    record = _convert(_result(repository_id=None))
    assert record.event.repository_id is None


def test_field_duration_ms_is_real_observed_value_never_estimated() -> None:
    record = _convert(_result(duration_ms=1234.5))
    assert record.event.duration_ms == 1234.5


def test_field_failure_category_preserved_when_present() -> None:
    result = _result(
        execution_status=AgentExecutionStatus.FAILED,
        verification_status=VerificationStatus.INCONCLUSIVE,
        failure_category=FailureCategory.PROVIDER_ERROR,
    )
    record = _convert(result)
    assert record.event.failure_category is FailureCategory.PROVIDER_ERROR


def test_field_failure_category_none_preserved_when_absent() -> None:
    record = _convert(_result())
    assert record.event.failure_category is None


def test_field_known_cost_preserved() -> None:
    record = _convert(_result(cost_usd=0.0123))
    assert record.event.cost_usd == 0.0123


def test_field_missing_cost_stays_none_never_zero() -> None:
    record = _convert(_result(cost_usd=None))
    assert record.event.cost_usd is None


def test_field_step_id_is_case_id_not_overloaded() -> None:
    record = _convert(_result(case_id="case-42"))
    assert record.event.step_id == "case-42"


def test_field_attempt_number_never_equals_repetition() -> None:
    """A benchmark repetition is an independent trial, not a retry --
    `attempt_number` must stay 1 regardless of `repetition`, or Stage 5's
    `retry_count`/Stage 5B's retry-history scoring would be corrupted."""
    record = _convert(_result(repetition=7))
    assert record.event.attempt_number == 1
    assert record.provenance.repetition == 7


# --- created_at handling ---------------------------------------------------------------------


def test_created_at_defaults_to_result_created_at() -> None:
    ts = datetime(2026, 3, 3, tzinfo=UTC)
    record = _convert(_result(created_at=ts))
    assert record.event.created_at == ts


def test_explicit_created_at_overrides_result_created_at() -> None:
    ts_result = datetime(2026, 3, 3, tzinfo=UTC)
    ts_override = datetime(2026, 4, 4, tzinfo=UTC)
    record = _convert(_result(created_at=ts_result), created_at=ts_override)
    assert record.event.created_at == ts_override


def test_missing_created_at_without_override_raises() -> None:
    with pytest.raises(MalformedBenchmarkLearningInputError, match="created_at"):
        _convert(_result(created_at=None))
