"""`BenchmarkLearningPolicy`: the single, explicit opt-in gate for using
benchmark-derived evidence at all.

**Conservative default.** `enabled=False` -- constructing the policy with
no arguments and calling `filter_records` always returns an empty list.
Nothing in this package makes benchmark evidence usable anywhere by
default; a caller must explicitly construct
`BenchmarkLearningPolicy(enabled=True)` (or pass one through) before any
`BenchmarkLearningRecord` survives filtering into a benchmark passport or
recommendation analysis. This mirrors Stage 7A's own "opt-in only" review
requirement one level up the pipeline.

**Honest evidence, not just successes.** `allow_passed`/`allow_failed`/
`allow_inconclusive`/`allow_human_review` all default to `True`: once
benchmark evidence is enabled at all, Stage 7B does not let a caller learn
only from `PASSED` outcomes by default -- that would silently bias
benchmark-derived passports toward optimism. A caller who genuinely wants
successes-only evidence can still set the other three flags `False`
explicitly.

**Not a weighting mechanism.** This policy only ever decides *whether* a
record is included, never *how much* it counts once included -- Stage 7B
performs no numeric down-weighting of benchmark evidence relative to
production evidence (see `adapter.py`'s module docstring). Any such
weighting is explicitly deferred to a future stage's own policy.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from app.contracts.verification import VerificationStatus
from app.engine.benchmark_learning.models import BenchmarkLearningRecord


@dataclass(frozen=True)
class BenchmarkLearningPolicy:
    """Controls whether, and which, benchmark-derived evidence may be used
    for anything beyond raw conversion. Stateless; `filter_records` is a
    pure function of its arguments."""

    enabled: bool = False
    allow_passed: bool = True
    allow_failed: bool = True
    allow_inconclusive: bool = True
    allow_human_review: bool = True

    def _allowed_verification_statuses(self) -> frozenset[VerificationStatus]:
        allowed: set[VerificationStatus] = set()
        if self.allow_passed:
            allowed.add(VerificationStatus.PASSED)
        if self.allow_failed:
            allowed.add(VerificationStatus.FAILED)
        if self.allow_inconclusive:
            allowed.add(VerificationStatus.INCONCLUSIVE)
        if self.allow_human_review:
            allowed.add(VerificationStatus.REQUIRES_HUMAN_REVIEW)
        return frozenset(allowed)

    def filter_records(
        self, records: Iterable[BenchmarkLearningRecord]
    ) -> list[BenchmarkLearningRecord]:
        """`[]` unconditionally when `enabled` is `False` -- the master
        opt-in switch. Otherwise keeps only records whose
        `verification_status` is allowed by the `allow_*` flags, preserving
        the input's relative order (callers wanting a canonical
        deterministic order should sort the result, or rely on the already-
        stably-ordered output of `adapter.convert_benchmark_results_to_learning_records`)."""
        if not self.enabled:
            return []
        allowed_statuses = self._allowed_verification_statuses()
        return [
            record
            for record in records
            if record.provenance.verification_status in allowed_statuses
        ]


__all__ = ["BenchmarkLearningPolicy"]
