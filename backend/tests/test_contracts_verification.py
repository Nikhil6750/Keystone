"""Tests for the Verifier's contracts: `VerificationResult`,
`VerificationEvidence`, `VerificationStatus`."""

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.contracts.enums import BenchmarkEvaluatorType
from app.contracts.verification import (
    VerificationEvidence,
    VerificationResult,
    VerificationStatus,
)

_NOW = datetime.now(UTC)


def _result(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "verification_id": "v1",
        "workflow_id": "wf-1",
        "evaluator_type": BenchmarkEvaluatorType.UNIT_TEST,
        "created_at": _NOW,
    }
    base.update(overrides)
    return base


def test_passed_result_forbids_a_failure_reason() -> None:
    with pytest.raises(ValidationError):
        VerificationResult.model_validate(
            _result(status=VerificationStatus.PASSED, failure_reason="should not be here")
        )


def test_passed_result_without_failure_reason_is_accepted() -> None:
    result = VerificationResult.model_validate(_result(status=VerificationStatus.PASSED))
    assert result.failure_reason is None


def test_failed_result_requires_a_non_blank_failure_reason() -> None:
    with pytest.raises(ValidationError):
        VerificationResult.model_validate(_result(status=VerificationStatus.FAILED))
    with pytest.raises(ValidationError):
        VerificationResult.model_validate(
            _result(status=VerificationStatus.FAILED, failure_reason="   ")
        )


def test_failed_result_with_reason_is_accepted() -> None:
    result = VerificationResult.model_validate(
        _result(status=VerificationStatus.FAILED, failure_reason="2 of 10 tests failed")
    )
    assert result.failure_reason == "2 of 10 tests failed"


def test_inconclusive_and_requires_human_review_have_no_failure_reason_requirement() -> None:
    inconclusive = VerificationResult.model_validate(
        _result(status=VerificationStatus.INCONCLUSIVE)
    )
    review = VerificationResult.model_validate(
        _result(status=VerificationStatus.REQUIRES_HUMAN_REVIEW)
    )
    assert inconclusive.failure_reason is None
    assert review.failure_reason is None


def test_confidence_must_be_between_zero_and_one() -> None:
    with pytest.raises(ValidationError):
        VerificationResult.model_validate(
            _result(status=VerificationStatus.PASSED, confidence=1.5)
        )
    with pytest.raises(ValidationError):
        VerificationResult.model_validate(
            _result(status=VerificationStatus.PASSED, confidence=-0.1)
        )


def test_confidence_boundary_values_are_accepted() -> None:
    low = VerificationResult.model_validate(
        _result(status=VerificationStatus.PASSED, confidence=0.0)
    )
    high = VerificationResult.model_validate(
        _result(status=VerificationStatus.PASSED, confidence=1.0)
    )
    assert low.confidence == 0.0
    assert high.confidence == 1.0


def test_verification_result_round_trips_through_json() -> None:
    result = VerificationResult.model_validate(
        _result(
            status=VerificationStatus.PASSED,
            step_id="step-1",
            confidence=0.9,
            reviewer_type="automated",
            evidence=[
                {"kind": "test_run", "description": "10/10 tests passed", "value": {"passed": 10}}
            ],
        )
    )
    restored = VerificationResult.model_validate_json(result.model_dump_json())
    assert restored == result


def test_verification_evidence_rejects_blank_kind_or_description() -> None:
    with pytest.raises(ValidationError):
        VerificationEvidence.model_validate({"kind": "  ", "description": "x"})
    with pytest.raises(ValidationError):
        VerificationEvidence.model_validate({"kind": "x", "description": ""})


def test_verification_evidence_rejects_reasoning_shaped_value() -> None:
    with pytest.raises(ValidationError):
        VerificationEvidence.model_validate(
            {
                "kind": "review",
                "description": "secondary review",
                "value": {"chain_of_thought": "x"},
            }
        )


def test_verification_evidence_accepts_plain_observable_value() -> None:
    evidence = VerificationEvidence.model_validate(
        {"kind": "exit_code", "description": "build exit code", "value": 0, "source": "ci"}
    )
    assert evidence.value == 0
    assert evidence.source == "ci"
