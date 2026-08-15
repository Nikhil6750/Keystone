"""The Verifier: "did it work?" -- turns one `ExpectedOutcome` +
`ObservedOutcome` pair into a `VerificationResult`, and a list of such pairs
into an `AggregatedVerification`.

Fully deterministic: `verification_id`/`workflow_id`/`step_id`/`created_at`
are always caller-supplied, never generated here (no `uuid4()`, no
`datetime.now()`) -- identical inputs always produce an identical
`VerificationResult`/`AggregatedVerification`, exactly like Stage 4C's
`DecisionTrace.created_at` reusing the decision's own timestamp rather than
calling `datetime.now()`.
"""

from dataclasses import dataclass
from datetime import datetime

from app.contracts.planning import ExpectedOutcome
from app.contracts.verification import VerificationResult
from app.engine.verification.aggregation import AggregatedVerification, CheckOutcome, aggregate
from app.engine.verification.evaluators import ObservedOutcome
from app.engine.verification.registry import get_evaluator


def verify_one(
    expected: ExpectedOutcome,
    observed: ObservedOutcome,
    *,
    verification_id: str,
    workflow_id: str,
    step_id: str | None = None,
    created_at: datetime,
) -> VerificationResult:
    """Evaluate one `ExpectedOutcome` against one `ObservedOutcome`."""
    evaluator = get_evaluator(expected.evaluator_type)
    outcome = evaluator(expected.criteria, observed)
    return VerificationResult(
        verification_id=verification_id,
        workflow_id=workflow_id,
        step_id=step_id,
        status=outcome.status,
        evaluator_type=expected.evaluator_type,
        evidence=outcome.evidence,
        confidence=outcome.confidence,
        failure_reason=outcome.failure_reason,
        reviewer_type=outcome.reviewer_type,
        created_at=created_at,
    )


@dataclass(frozen=True)
class VerificationCheck:
    """One `ExpectedOutcome`/`ObservedOutcome` pair to verify, and whether
    it is required for an overall `PASSED` (see `aggregation.py`).
    `TaskSpec.expected_outcome` is singular -- this engine-layer type is
    what lets a caller check a single task's output against several
    distinct criteria (e.g. `build` AND `lint` AND `unit_test`) without any
    change to the `TaskSpec`/`ExpectedOutcome` contracts."""

    expected: ExpectedOutcome
    observed: ObservedOutcome
    required: bool = True
    label: str | None = None

    def __post_init__(self) -> None:
        if self.label is not None and not self.label.strip():
            raise ValueError("label must not be blank if provided")


def verify_many(
    checks: list[VerificationCheck],
    *,
    workflow_id: str,
    step_id: str | None = None,
    verification_id_prefix: str,
    created_at: datetime,
) -> AggregatedVerification:
    """Verify every check and deterministically aggregate the result.
    `verification_id`s are derived from `verification_id_prefix` and each
    check's position (never random), so repeated calls with identical
    `checks` produce identical `VerificationResult.verification_id`s too."""
    outcomes = [
        CheckOutcome(
            result=verify_one(
                check.expected,
                check.observed,
                verification_id=f"{verification_id_prefix}-{index}",
                workflow_id=workflow_id,
                step_id=step_id,
                created_at=created_at,
            ),
            required=check.required,
            label=check.label,
        )
        for index, check in enumerate(checks)
    ]
    return aggregate(outcomes, created_at=created_at)


__all__ = ["VerificationCheck", "verify_many", "verify_one"]
