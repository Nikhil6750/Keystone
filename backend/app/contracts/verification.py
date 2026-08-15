"""Verification contracts: "did the executed result satisfy the intended
outcome?"

Data shapes only — no evaluator logic lives here. Reuses
`BenchmarkEvaluatorType` (`app.contracts.enums`) rather than a second
objective-evaluator taxonomy: Stage 4 live verification and Stage 7
benchmarking answer the same underlying question ("does this output satisfy
these objective criteria?") and should never grow two incompatible
vocabularies for it.

Every field here must describe Keystone's own observable, measurable
evidence — test results, exit codes, diffs, human/secondary-agent
sign-off — never a model's internal reasoning. `VerificationEvidence.value`
is checked recursively for reserved reasoning-trace-shaped dict keys via
`app.contracts.evidence_safety` (shared with `app.contracts.explainability`);
nothing in this module can substitute for disciplined field design, but see
`docs/contracts.md` for the full rule.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.contracts.enums import BenchmarkEvaluatorType
from app.contracts.evidence_safety import reject_reasoning_shaped_keys


class VerificationStatus(StrEnum):
    """The outcome of one verification check."""

    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"
    REQUIRES_HUMAN_REVIEW = "requires_human_review"


class VerificationEvidence(BaseModel):
    """One piece of observable evidence backing a `VerificationResult` — a
    test count, an exit code, a diff, a reviewer's sign-off. Never a model's
    internal reasoning."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    description: str
    value: Any = None
    source: str | None = None
    timestamp: datetime | None = None

    @field_validator("kind", "description")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("value")
    @classmethod
    def _value_not_reasoning_shaped(cls, value: Any) -> Any:
        return reject_reasoning_shaped_keys(value)


class VerificationResult(BaseModel):
    """The outcome of verifying one execution result against its
    `ExpectedOutcome` (`app.contracts.planning`).

    `failure_reason` behavior by `status` — the only two combinations with
    an unambiguous expectation are enforced; the other two are deliberately
    left to the caller's judgment:

    - `PASSED`: `failure_reason` must be `None` (there is nothing to explain).
    - `FAILED`: `failure_reason` is required and must not be blank.
    - `INCONCLUSIVE`: `failure_reason` is optional — a caller may note *why*
      the check could not reach a verdict (e.g. "evaluator timed out"), or
      leave it `None` when there's nothing more to say than "inconclusive."
    - `REQUIRES_HUMAN_REVIEW`: `failure_reason` is optional, for the same
      reason — it may carry context for the reviewer, or be left `None`.
    """

    model_config = ConfigDict(from_attributes=True)

    verification_id: str
    workflow_id: str
    step_id: str | None = None
    status: VerificationStatus
    evaluator_type: BenchmarkEvaluatorType
    evidence: list[VerificationEvidence] = Field(default_factory=list)
    confidence: float | None = None
    failure_reason: str | None = None
    reviewer_type: str | None = None
    created_at: datetime

    @field_validator("confidence")
    @classmethod
    def _confidence_bounded(cls, value: float | None) -> float | None:
        if value is not None and not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return value

    @model_validator(mode="after")
    def _status_failure_reason_consistency(self) -> "VerificationResult":
        """Enforce the `status` <-> `failure_reason` pairing for the two
        statuses with an unambiguous expectation. Never rewrites the input
        to make it consistent — an inconsistent combination is a caller bug
        and must fail loudly."""
        if self.status is VerificationStatus.PASSED and self.failure_reason is not None:
            raise ValueError("failure_reason must be None when status is PASSED")
        if self.status is VerificationStatus.FAILED and not (
            self.failure_reason and self.failure_reason.strip()
        ):
            raise ValueError(
                "failure_reason is required and must not be blank when status is FAILED"
            )
        return self


__all__ = ["VerificationEvidence", "VerificationResult", "VerificationStatus"]
