"""Deterministic, transparent recommendation scoring.

Every component is a plain function of already-aggregated
`AgentPassportMetricBucket`/`VerificationMetrics` fields -- no randomness,
no `datetime.now()`, no external model call. Mirrors Stage 4B's
scorer.py formulas (Beta(1,1)-smoothed reliability, `target_latency_ms`-
relative latency scoring, explicit named weight constants) deliberately,
so Stage 5A/5B evidence "feels" consistent with Stage 4B's own scoring --
but this module is entirely independent: it never imports
`app.engine.routing.scorer`, and nothing here is consumed by the Router.

**Cancellation stays neutral.** `execution_reliability` is computed over
`success_count + failure_count` only, never `execution_count` (which also
includes cancellations) -- a cancelled-only execution contributes to
neither the numerator nor the denominator, so it cannot silently drag the
reliability score down. Stage 5A's own bucket construction already
excludes cancellations from `success_count`/`failure_count`; this module
just also excludes them from the reliability *denominator*, which
`execution_count` alone would not.

**Verified success is primary.** The weighted base score exists only to
rank candidates that already cleared the minimum verified-sample gate
(`policy.py`'s tier selection) -- this module never invents a score for
evidence too thin to support one.
"""

import math
from dataclasses import dataclass

from app.contracts.passports import AgentPassportMetricBucket
from app.engine.learning.errors import LearningEngineError

_RELIABILITY_PRIOR_SUCCESSES = 1.0
_RELIABILITY_PRIOR_STRENGTH = 2.0
_NEUTRAL_SCORE = 0.5


@dataclass(frozen=True)
class RecommendationWeights:
    """Explicit, documented weights combining four normalized `[0, 1]`
    factors into one composite recommendation score, also in `[0, 1]`:

    - `verified_success_weight` (default `0.55`): the primary signal --
      Stage 4E-verified outcome quality, never conflated with mere
      execution success.
    - `execution_reliability_weight` (default `0.20`): Beta(1,1)-smoothed
      execution success ratio (transport-level: did the process return
      successfully), a secondary signal.
    - `latency_weight` (default `0.15`): `target_latency_ms`-relative
      latency, neutral (`0.5`) when no latency evidence exists.
    - `capability_support_weight` (default `0.10`): optional supporting
      evidence from a matching capability bucket, neutral (`0.5`) when no
      capability was requested or no sufficiently-sampled capability
      evidence exists -- this can only ever help rank agents already being
      compared, never substitute for the Router's own hard
      required-capability check.

    These four sum to `1.0`. Two further terms are *subtracted* from that
    weighted sum rather than folded into it, since they are penalties for
    observed friction, not positive evidence of quality:

    - `verification_failure_penalty_strength` (default `0.30`): multiplies
      the bucket's own verification-failure rate.
    - `retry_penalty_strength` (default `0.10`): multiplies the agent's
      overall retry rate (retries are only tracked at the whole-passport
      level in Stage 5A, so this penalty is agent-wide, not bucket-scoped).

    `avoid_threshold` (default `0.5`): a candidate with sufficient evidence
    whose `verified_success_rate` falls below this is `AVOID_IF_POSSIBLE`
    rather than `RECOMMEND` -- a majority-verified-failing track record is
    never recommended, however it scores on other factors.
    """

    verified_success_weight: float = 0.55
    execution_reliability_weight: float = 0.20
    latency_weight: float = 0.15
    capability_support_weight: float = 0.10
    verification_failure_penalty_strength: float = 0.30
    retry_penalty_strength: float = 0.10
    avoid_threshold: float = 0.5
    target_latency_ms: float = 5000.0

    def __post_init__(self) -> None:
        base_weights = (
            self.verified_success_weight,
            self.execution_reliability_weight,
            self.latency_weight,
            self.capability_support_weight,
        )
        if min(base_weights) < 0:
            raise LearningEngineError("recommendation weights must not be negative")
        total = sum(base_weights)
        if abs(total - 1.0) > 1e-9:
            raise LearningEngineError(f"recommendation weights must sum to 1.0, got {total}")
        if self.verification_failure_penalty_strength < 0 or self.retry_penalty_strength < 0:
            raise LearningEngineError("penalty strengths must not be negative")
        if self.target_latency_ms <= 0:
            raise LearningEngineError("target_latency_ms must be positive")
        if not 0.0 <= self.avoid_threshold <= 1.0:
            raise LearningEngineError("avoid_threshold must be between 0 and 1")


def execution_reliability(metrics: AgentPassportMetricBucket) -> float:
    """Beta(1,1)-smoothed success ratio over `success_count + failure_count`
    (deliberately excluding cancellations -- see module docstring). `0.5`
    (neutral) when there is no relevant evidence at all."""
    relevant = metrics.success_count + metrics.failure_count
    if relevant == 0:
        return _NEUTRAL_SCORE
    smoothed = (metrics.success_count + _RELIABILITY_PRIOR_SUCCESSES) / (
        relevant + _RELIABILITY_PRIOR_STRENGTH
    )
    if not math.isfinite(smoothed):
        return _NEUTRAL_SCORE
    return max(0.0, min(1.0, smoothed))


def latency_component(median_latency_ms: float | None, target_latency_ms: float) -> float:
    """`target_latency_ms / median_latency_ms`, clamped to `[0, 1]`. `0.5`
    (neutral) when no latency evidence exists -- never penalized, never
    rewarded for absence."""
    if median_latency_ms is None or median_latency_ms <= 0:
        return _NEUTRAL_SCORE
    score = target_latency_ms / median_latency_ms
    if not math.isfinite(score):
        return _NEUTRAL_SCORE
    return max(0.0, min(1.0, score))


__all__ = ["RecommendationWeights", "execution_reliability", "latency_component"]
