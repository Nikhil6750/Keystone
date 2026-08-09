"""Stage 7.5 evidence-hierarchy tier selection and bounded score adjustment.

**Evidence hierarchy** (most to least specific), mirroring Stage 5B's own
tier order (`app.engine.learning.policy._select_tier`) -- each tier is
used only when it independently clears `policy.minimum_verified_samples`;
a thin, highly-specific bucket never overrides a broader, well-sampled one
just because it is more specific:

    1. repository + task type
    2. task type
    3. repository
    4. overall
    5. insufficient/no evidence -> neutral (zero) adjustment

**Production before benchmark, never blended.** `select_adjustment` tries
`production_passport` first; only if no tier there clears the sample gate
*and* `policy.allow_benchmark_evidence` is `True` does it fall back to
`benchmark_passport`. The two are never combined into one rate -- exactly
one of them (or neither) ever contributes to a given chunk's adjustment.

**Bounded, deterministic adjustment formula.** For the selected tier's
`verified_success_rate` (guaranteed non-`None` once a tier clears the
sample gate):

    signal = (verified_success_rate - 0.5) * 2       # in [-1.0, 1.0]
    adjustment = signal * max_positive_adjustment      if signal >= 0
                 signal * max_negative_adjustment       if signal < 0

`verified_success_rate = 0.5` (as much verified success as failure) is the
neutral point, contributing zero adjustment -- a chunk needs a genuinely
lopsided verified track record to move at all, and even a perfect `1.0`/`0.0`
rate can never move the score by more than `policy.max_positive_adjustment`/
`policy.max_negative_adjustment`. This is an explicit, documented formula,
not a fitted or "trust me" ML weight -- every input to it is a plain count
already visible on the chosen `RetrievalBucket`.
"""

from dataclasses import dataclass

from app.engine.adaptive_retrieval.passport import RetrievalBucket, RetrievalPassport
from app.engine.adaptive_retrieval.policy import AdaptiveRetrievalPolicy

_TIER_ORDER = ("repository_task_type", "task_type", "repository", "overall")


@dataclass(frozen=True)
class SelectedEvidence:
    """Which tier, of which evidence source, actually backed an
    adjustment -- fully explainable, never a hidden blend."""

    source: str  # "production" | "benchmark" | "none"
    tier: str  # one of _TIER_ORDER, or "none"
    bucket: RetrievalBucket | None


def _tier_bucket(
    passport: RetrievalPassport, tier: str, *, task_type: str | None, repository_id: str | None
) -> RetrievalBucket | None:
    if tier == "repository_task_type":
        if repository_id is None or task_type is None:
            return None
        return passport.repository_task_type_buckets.get((repository_id, task_type))
    if tier == "task_type":
        if task_type is None:
            return None
        return passport.task_type_buckets.get(task_type)
    if tier == "repository":
        if repository_id is None:
            return None
        return passport.repository_buckets.get(repository_id)
    return passport.overall  # "overall" always exists


def _select_tier_for_passport(
    passport: RetrievalPassport,
    *,
    task_type: str | None,
    repository_id: str | None,
    minimum_verified_samples: int,
) -> tuple[str, RetrievalBucket] | None:
    """The most specific `(tier_name, bucket)` whose
    `verification_sample_count` clears `minimum_verified_samples`, or
    `None` if no tier does."""
    for tier in _TIER_ORDER:
        bucket = _tier_bucket(passport, tier, task_type=task_type, repository_id=repository_id)
        if bucket is not None and (
            bucket.verification.verification_sample_count >= minimum_verified_samples
        ):
            return tier, bucket
    return None


def select_evidence(
    *,
    production_passport: RetrievalPassport | None,
    benchmark_passport: RetrievalPassport | None,
    task_type: str | None,
    repository_id: str | None,
    policy: AdaptiveRetrievalPolicy,
) -> SelectedEvidence:
    """Walk the evidence hierarchy for one chunk: production first (if
    `policy.allow_production_evidence`), then benchmark as a fallback only
    (if `policy.allow_benchmark_evidence` and production found nothing
    sufficient). Never both at once."""
    if policy.allow_production_evidence and production_passport is not None:
        found = _select_tier_for_passport(
            production_passport,
            task_type=task_type,
            repository_id=repository_id,
            minimum_verified_samples=policy.minimum_verified_samples,
        )
        if found is not None:
            tier, bucket = found
            return SelectedEvidence(source="production", tier=tier, bucket=bucket)

    if policy.allow_benchmark_evidence and benchmark_passport is not None:
        found = _select_tier_for_passport(
            benchmark_passport,
            task_type=task_type,
            repository_id=repository_id,
            minimum_verified_samples=policy.minimum_verified_samples,
        )
        if found is not None:
            tier, bucket = found
            return SelectedEvidence(source="benchmark", tier=tier, bucket=bucket)

    return SelectedEvidence(source="none", tier="none", bucket=None)


def bounded_adjustment(evidence: SelectedEvidence, *, policy: AdaptiveRetrievalPolicy) -> float:
    """The deterministic, bounded score adjustment for `evidence` -- `0.0`
    when `evidence.bucket` is `None` (no sufficient evidence at any tier).
    Always within `[-policy.max_negative_adjustment,
    policy.max_positive_adjustment]`."""
    if evidence.bucket is None:
        return 0.0
    rate = evidence.bucket.verification.verified_success_rate
    if rate is None:
        return 0.0  # sample gate should prevent this, but never trust a None rate as a signal

    signal = (rate - 0.5) * 2.0  # in [-1.0, 1.0]
    if signal >= 0.0:
        return signal * policy.max_positive_adjustment
    return signal * policy.max_negative_adjustment


__all__ = ["SelectedEvidence", "bounded_adjustment", "select_evidence"]
