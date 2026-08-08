"""Deterministic aggregation of multiple `VerificationResult`s into one
overall `VerificationStatus`.

**Rules (documented, no probabilistic scoring):**

1. Only `required=True` checks affect `overall_status`. An optional check's
   status never overrides a required failure and never contributes to a
   PASSED verdict on its own -- it is still preserved in `checks` for full
   evidence/explainability visibility, just excluded from the decision.
2. If any required check is `FAILED`, `overall_status` is `FAILED`.
3. Else if any required check is `REQUIRES_HUMAN_REVIEW`, `overall_status`
   is `REQUIRES_HUMAN_REVIEW`.
4. Else if any required check is `INCONCLUSIVE` (including a check whose
   evidence was simply missing -- see `evaluators.py`), `overall_status` is
   `INCONCLUSIVE`. Missing required evidence can never become `PASSED`.
5. Only if every required check is `PASSED` (and at least one required
   check exists) is `overall_status` `PASSED`. Zero required checks is
   itself `INCONCLUSIVE` -- "nothing was objectively required and checked"
   is never silently treated as success.

This priority order (`FAILED > REQUIRES_HUMAN_REVIEW > INCONCLUSIVE >
PASSED`) is a fixed table, not a computed score, and ties within one
priority level never affect which `overall_status` is chosen (only which
checks are *named* in `summary`, which lists every required check at the
worst level found, not just the first).
"""

from dataclasses import dataclass, field
from datetime import datetime

from app.contracts.verification import VerificationResult, VerificationStatus

_STATUS_PRIORITY: dict[VerificationStatus, int] = {
    VerificationStatus.FAILED: 0,
    VerificationStatus.REQUIRES_HUMAN_REVIEW: 1,
    VerificationStatus.INCONCLUSIVE: 2,
    VerificationStatus.PASSED: 3,
}


@dataclass(frozen=True)
class CheckOutcome:
    """One verified check plus whether it was required for an overall PASSED."""

    result: VerificationResult
    required: bool = True
    label: str | None = None

    def __post_init__(self) -> None:
        if self.label is not None and not self.label.strip():
            raise ValueError("label must not be blank if provided")


@dataclass(frozen=True)
class AggregatedVerification:
    """The deterministic combination of every `CheckOutcome` into one verdict."""

    overall_status: VerificationStatus
    checks: list[CheckOutcome] = field(default_factory=list)
    summary: str = ""
    created_at: datetime | None = None


def _check_label(check: CheckOutcome) -> str:
    return check.label or check.result.evaluator_type.value


def aggregate(checks: list[CheckOutcome], *, created_at: datetime) -> AggregatedVerification:
    """Combine `checks` into one `AggregatedVerification`. See module
    docstring for the exact rule table. Deterministic: identical `checks`
    (in identical order) always produce an identical `overall_status` and
    `summary`."""
    required = [check for check in checks if check.required]

    if not required:
        return AggregatedVerification(
            overall_status=VerificationStatus.INCONCLUSIVE,
            checks=checks,
            summary="no required checks were provided; nothing was objectively verified",
            created_at=created_at,
        )

    worst_priority = min(_STATUS_PRIORITY[check.result.status] for check in required)
    overall_status = next(
        status for status, priority in _STATUS_PRIORITY.items() if priority == worst_priority
    )

    if overall_status is VerificationStatus.PASSED:
        summary = f"all {len(required)} required check(s) passed"
    else:
        offending = [check for check in required if check.result.status is overall_status]
        names = ", ".join(_check_label(check) for check in offending)
        summary = (
            f"{len(offending)} of {len(required)} required check(s) resulted in "
            f"{overall_status.value}: {names}"
        )

    return AggregatedVerification(
        overall_status=overall_status, checks=checks, summary=summary, created_at=created_at
    )


__all__ = ["AggregatedVerification", "CheckOutcome", "aggregate"]
