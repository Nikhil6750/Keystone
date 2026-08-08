"""Tests for `app.engine.verification.verifier`: `verify_one`/`verify_many`
orchestration -- turning `ExpectedOutcome`/`ObservedOutcome` pairs into
`VerificationResult`/`AggregatedVerification`."""

from datetime import UTC, datetime

import pytest

from app.contracts.enums import BenchmarkEvaluatorType
from app.contracts.planning import ExpectedOutcome
from app.contracts.verification import VerificationStatus
from app.engine.verification.errors import MalformedExpectedOutcomeError, UnsupportedEvaluatorError
from app.engine.verification.evaluators import ObservedOutcome
from app.engine.verification.verifier import VerificationCheck, verify_many, verify_one

_NOW = datetime.now(UTC)


def _outcome(
    evaluator_type: BenchmarkEvaluatorType, criteria: dict[str, object]
) -> ExpectedOutcome:
    return ExpectedOutcome(evaluator_type=evaluator_type, criteria=criteria)


def test_verify_one_returns_passed_verification_result() -> None:
    result = verify_one(
        _outcome(BenchmarkEvaluatorType.EXIT_CODE, {}),
        ObservedOutcome({"exit_code": 0}),
        verification_id="v1",
        workflow_id="wf-1",
        step_id="step-a",
        created_at=_NOW,
    )
    assert result.status is VerificationStatus.PASSED
    assert result.verification_id == "v1"
    assert result.workflow_id == "wf-1"
    assert result.step_id == "step-a"
    assert result.evaluator_type is BenchmarkEvaluatorType.EXIT_CODE


def test_verify_one_raises_typed_error_for_unsupported_evaluator_type() -> None:
    outcome = ExpectedOutcome.model_construct(evaluator_type="not_real", criteria={})
    with pytest.raises(UnsupportedEvaluatorError):
        verify_one(
            outcome, ObservedOutcome({}), verification_id="v1", workflow_id="wf-1", created_at=_NOW
        )


def test_verify_one_raises_typed_error_for_malformed_criteria() -> None:
    with pytest.raises(MalformedExpectedOutcomeError):
        verify_one(
            _outcome(BenchmarkEvaluatorType.EXACT_MATCH, {}),
            ObservedOutcome({"output": "x"}),
            verification_id="v1",
            workflow_id="wf-1",
            created_at=_NOW,
        )


def test_verify_many_all_required_checks_pass() -> None:
    checks = [
        VerificationCheck(
            expected=_outcome(BenchmarkEvaluatorType.EXIT_CODE, {}),
            observed=ObservedOutcome({"exit_code": 0}),
        ),
        VerificationCheck(
            expected=_outcome(BenchmarkEvaluatorType.UNIT_TEST, {}),
            observed=ObservedOutcome({"exit_code": 0, "tests_total": 5, "tests_failed": 0}),
        ),
    ]
    aggregated = verify_many(
        checks, workflow_id="wf-1", verification_id_prefix="wf-1-v", created_at=_NOW
    )
    assert aggregated.overall_status is VerificationStatus.PASSED
    assert len(aggregated.checks) == 2


def test_verify_many_required_check_fails() -> None:
    checks = [
        VerificationCheck(
            expected=_outcome(BenchmarkEvaluatorType.EXIT_CODE, {}),
            observed=ObservedOutcome({"exit_code": 1}),
        )
    ]
    aggregated = verify_many(
        checks, workflow_id="wf-1", verification_id_prefix="wf-1-v", created_at=_NOW
    )
    assert aggregated.overall_status is VerificationStatus.FAILED


def test_verify_many_optional_check_failure_does_not_block_pass() -> None:
    checks = [
        VerificationCheck(
            expected=_outcome(BenchmarkEvaluatorType.EXIT_CODE, {}),
            observed=ObservedOutcome({"exit_code": 0}),
        ),
        VerificationCheck(
            expected=_outcome(BenchmarkEvaluatorType.LINT, {"max_violations": 0}),
            observed=ObservedOutcome({"exit_code": 0, "violation_count": 3}),
            required=False,
        ),
    ]
    aggregated = verify_many(
        checks, workflow_id="wf-1", verification_id_prefix="wf-1-v", created_at=_NOW
    )
    assert aggregated.overall_status is VerificationStatus.PASSED


def test_verify_many_missing_required_evidence_is_inconclusive_not_pass() -> None:
    checks = [
        VerificationCheck(
            expected=_outcome(BenchmarkEvaluatorType.EXIT_CODE, {}), observed=ObservedOutcome({})
        )
    ]
    aggregated = verify_many(
        checks, workflow_id="wf-1", verification_id_prefix="wf-1-v", created_at=_NOW
    )
    assert aggregated.overall_status is VerificationStatus.INCONCLUSIVE


def test_verify_many_human_review_requirement_surfaces_at_top_level() -> None:
    checks = [
        VerificationCheck(
            expected=_outcome(BenchmarkEvaluatorType.HUMAN_REVIEWED, {}),
            observed=ObservedOutcome({}),
        )
    ]
    aggregated = verify_many(
        checks, workflow_id="wf-1", verification_id_prefix="wf-1-v", created_at=_NOW
    )
    assert aggregated.overall_status is VerificationStatus.REQUIRES_HUMAN_REVIEW


def test_verify_many_verification_ids_are_derived_not_random() -> None:
    checks = [
        VerificationCheck(
            expected=_outcome(BenchmarkEvaluatorType.EXIT_CODE, {}),
            observed=ObservedOutcome({"exit_code": 0}),
        ),
        VerificationCheck(
            expected=_outcome(BenchmarkEvaluatorType.EXIT_CODE, {}),
            observed=ObservedOutcome({"exit_code": 0}),
        ),
    ]
    aggregated = verify_many(
        checks, workflow_id="wf-1", verification_id_prefix="wf-1-v", created_at=_NOW
    )
    ids = [check.result.verification_id for check in aggregated.checks]
    assert ids == ["wf-1-v-0", "wf-1-v-1"]


def test_verify_many_is_deterministic() -> None:
    checks = [
        VerificationCheck(
            expected=_outcome(BenchmarkEvaluatorType.EXIT_CODE, {}),
            observed=ObservedOutcome({"exit_code": 0}),
        )
    ]
    first = verify_many(checks, workflow_id="wf-1", verification_id_prefix="v", created_at=_NOW)
    for _ in range(20):
        again = verify_many(checks, workflow_id="wf-1", verification_id_prefix="v", created_at=_NOW)
        assert again.overall_status == first.overall_status
        assert again.checks[0].result.verification_id == first.checks[0].result.verification_id
