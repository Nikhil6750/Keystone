"""Tests for `app.engine.verification.aggregation`: deterministic combination
of multiple `VerificationResult`s into one overall `VerificationStatus`."""

from datetime import UTC, datetime

from app.contracts.enums import BenchmarkEvaluatorType
from app.contracts.verification import VerificationResult, VerificationStatus
from app.engine.verification.aggregation import CheckOutcome, aggregate

_NOW = datetime.now(UTC)


def _result(status: VerificationStatus, *, failure_reason: str | None = None) -> VerificationResult:
    return VerificationResult(
        verification_id="v1",
        workflow_id="wf-1",
        status=status,
        evaluator_type=BenchmarkEvaluatorType.UNIT_TEST,
        failure_reason=failure_reason,
        created_at=_NOW,
    )


def test_all_required_checks_pass() -> None:
    checks = [
        CheckOutcome(result=_result(VerificationStatus.PASSED), required=True),
        CheckOutcome(result=_result(VerificationStatus.PASSED), required=True),
    ]
    aggregated = aggregate(checks, created_at=_NOW)
    assert aggregated.overall_status is VerificationStatus.PASSED


def test_one_required_failure_prevents_passed() -> None:
    checks = [
        CheckOutcome(result=_result(VerificationStatus.PASSED), required=True),
        CheckOutcome(
            result=_result(VerificationStatus.FAILED, failure_reason="x"), required=True
        ),
    ]
    aggregated = aggregate(checks, created_at=_NOW)
    assert aggregated.overall_status is VerificationStatus.FAILED


def test_multiple_failures_still_resolve_to_failed_and_are_named() -> None:
    checks = [
        CheckOutcome(
            result=_result(VerificationStatus.FAILED, failure_reason="a"),
            required=True,
            label="build",
        ),
        CheckOutcome(
            result=_result(VerificationStatus.FAILED, failure_reason="b"),
            required=True,
            label="lint",
        ),
    ]
    aggregated = aggregate(checks, created_at=_NOW)
    assert aggregated.overall_status is VerificationStatus.FAILED
    assert "build" in aggregated.summary
    assert "lint" in aggregated.summary


def test_missing_required_evidence_prevents_passed() -> None:
    checks = [CheckOutcome(result=_result(VerificationStatus.INCONCLUSIVE), required=True)]
    aggregated = aggregate(checks, created_at=_NOW)
    assert aggregated.overall_status is VerificationStatus.INCONCLUSIVE


def test_optional_failure_cannot_mask_success_or_pull_down_result() -> None:
    checks = [
        CheckOutcome(result=_result(VerificationStatus.PASSED), required=True),
        CheckOutcome(
            result=_result(VerificationStatus.FAILED, failure_reason="optional broke"),
            required=False,
        ),
    ]
    aggregated = aggregate(checks, created_at=_NOW)
    assert aggregated.overall_status is VerificationStatus.PASSED


def test_optional_pass_cannot_rescue_a_required_failure() -> None:
    checks = [
        CheckOutcome(result=_result(VerificationStatus.FAILED, failure_reason="x"), required=True),
        CheckOutcome(result=_result(VerificationStatus.PASSED), required=False),
    ]
    aggregated = aggregate(checks, created_at=_NOW)
    assert aggregated.overall_status is VerificationStatus.FAILED


def test_required_human_review_outranks_required_inconclusive() -> None:
    checks = [
        CheckOutcome(result=_result(VerificationStatus.INCONCLUSIVE), required=True),
        CheckOutcome(result=_result(VerificationStatus.REQUIRES_HUMAN_REVIEW), required=True),
    ]
    aggregated = aggregate(checks, created_at=_NOW)
    assert aggregated.overall_status is VerificationStatus.REQUIRES_HUMAN_REVIEW


def test_required_failed_outranks_required_human_review() -> None:
    checks = [
        CheckOutcome(result=_result(VerificationStatus.REQUIRES_HUMAN_REVIEW), required=True),
        CheckOutcome(result=_result(VerificationStatus.FAILED, failure_reason="x"), required=True),
    ]
    aggregated = aggregate(checks, created_at=_NOW)
    assert aggregated.overall_status is VerificationStatus.FAILED


def test_zero_required_checks_is_inconclusive_even_if_optional_all_pass() -> None:
    checks = [CheckOutcome(result=_result(VerificationStatus.PASSED), required=False)]
    aggregated = aggregate(checks, created_at=_NOW)
    assert aggregated.overall_status is VerificationStatus.INCONCLUSIVE


def test_empty_checks_list_is_inconclusive() -> None:
    aggregated = aggregate([], created_at=_NOW)
    assert aggregated.overall_status is VerificationStatus.INCONCLUSIVE


def test_aggregation_preserves_every_individual_check() -> None:
    checks = [
        CheckOutcome(result=_result(VerificationStatus.PASSED), required=True, label="build"),
        CheckOutcome(result=_result(VerificationStatus.PASSED), required=False, label="lint"),
    ]
    aggregated = aggregate(checks, created_at=_NOW)
    assert aggregated.checks == checks


def test_aggregation_is_deterministic() -> None:
    checks = [
        CheckOutcome(result=_result(VerificationStatus.PASSED), required=True),
        CheckOutcome(result=_result(VerificationStatus.FAILED, failure_reason="x"), required=True),
    ]
    first = aggregate(checks, created_at=_NOW)
    for _ in range(20):
        again = aggregate(checks, created_at=_NOW)
        assert again.overall_status == first.overall_status
        assert again.summary == first.summary
