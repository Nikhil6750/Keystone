"""`LearningPolicy`: "based on historical VERIFIED evidence, what should
Keystone recommend?"

    LearningPolicy.recommend(...)
            |
            v
    LearningRecommendation
            |
            v
    future Manager/Orchestrator may use this as advisory evidence
            |
            v
    Router still makes the final route decision

**Stage 5B does not replace the Router.** `app.engine.routing.router.Router`
remains the sole authority for hard constraints, capability eligibility,
availability, circuit-breaker state, cost/latency/reliability constraints,
and the final deterministic ranking. This module is never imported by
`Router`/`app.engine.routing.scorer`, never calls either of them, and
produces only an advisory `LearningRecommendation` -- there is no code path
anywhere in this package that automatically overrides or bypasses a
routing decision.

**Evidence hierarchy** (most to least specific), each tier only used when
it independently clears the minimum verified-sample gate
(`MIN_SAMPLE_SIZE_FOR_CONFIDENCE`, reused from `aggregation.py`) -- a
narrow, thinly-sampled bucket never overrides a broader, well-sampled one:

    1. repository + task-type (`LearningPassport.repository_task_type_buckets`)
    2. task-type (`task_type_buckets`)
    3. repository (`repository_buckets`)
    4. overall agent evidence
    5. insufficient evidence / bootstrap (`INSUFFICIENT_EVIDENCE`/`NO_EVIDENCE`)

Capability evidence (`capability_buckets`) is never its own hierarchy tier
-- per the Stage 5B spec, it only ever contributes optional *supporting*
evidence to the score of whichever tier was actually selected, and only
when it is itself sufficiently sampled. It can never make an
otherwise-ineligible agent "count," and it never touches Router capability
*eligibility* at all -- Stage 5B has no concept of a required capability,
only optional scoring support among agents already being compared.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from app.contracts.enums import AgentCapability
from app.engine.learning.aggregation import (
    MIN_SAMPLE_SIZE_FOR_CONFIDENCE,
    LearningBucket,
)
from app.engine.learning.errors import LearningEngineError
from app.engine.learning.passport import LearningPassport
from app.engine.learning.recommendation import (
    CAPABILITY_VERIFIED_HISTORY,
    LOW_SAMPLE_SIZE,
    NO_VERIFIED_EVIDENCE,
    OVERALL_VERIFIED_HISTORY,
    REPOSITORY_VERIFIED_HISTORY,
    RETRY_HISTORY,
    TASK_TYPE_VERIFIED_HISTORY,
    VERIFICATION_FAILURE_HISTORY,
    AgentRecommendation,
    LearningRecommendation,
    RecommendationOutcome,
)
from app.engine.learning.scoring import (
    RecommendationWeights,
    execution_reliability,
    latency_component,
)

# Reason-code threshold constants -- explicit, documented, never tuned by
# feel: a verification-failure rate or retry rate above these fractions
# earns the corresponding explainability reason code (on top of always
# factoring into the score via `RecommendationWeights`' penalty strengths).
_VERIFICATION_FAILURE_HISTORY_THRESHOLD = 0.3
_RETRY_HISTORY_THRESHOLD = 0.2

_TIER_REASON_CODES: dict[str, tuple[str, ...]] = {
    "repository_task_type": (REPOSITORY_VERIFIED_HISTORY, TASK_TYPE_VERIFIED_HISTORY),
    "task_type": (TASK_TYPE_VERIFIED_HISTORY,),
    "repository": (REPOSITORY_VERIFIED_HISTORY,),
    "overall": (OVERALL_VERIFIED_HISTORY,),
}

_TIER_PHRASES: dict[str, str] = {
    "repository_task_type": "for this task type in this repository",
    "task_type": "for this task type",
    "repository": "for this repository",
    "overall": "overall",
}


@dataclass(frozen=True)
class _TierEvidence:
    """The result of walking the evidence hierarchy for one agent: which
    tier was used, its bucket (if any evidence existed at all there), and
    whether that bucket independently cleared the minimum verified-sample
    gate."""

    tier: str
    bucket: LearningBucket | None
    sufficient: bool


def _select_tier(
    passport: LearningPassport, *, task_type: str, repository_id: str | None
) -> _TierEvidence:
    ordered: list[tuple[str, LearningBucket]] = []
    if repository_id is not None:
        joint = passport.repository_task_type_buckets.get((repository_id, task_type))
        if joint is not None:
            ordered.append(("repository_task_type", joint))
    task_bucket = passport.task_type_buckets.get(task_type)
    if task_bucket is not None:
        ordered.append(("task_type", task_bucket))
    if repository_id is not None:
        repository_bucket = passport.repository_buckets.get(repository_id)
        if repository_bucket is not None:
            ordered.append(("repository", repository_bucket))
    overall_bucket = LearningBucket(
        metrics=passport.overall_metrics, verification=passport.overall_verification
    )
    ordered.append(("overall", overall_bucket))

    for tier, bucket in ordered:
        if bucket.verification.verification_sample_count >= MIN_SAMPLE_SIZE_FOR_CONFIDENCE:
            return _TierEvidence(tier=tier, bucket=bucket, sufficient=True)

    # No tier independently cleared the minimum verified-sample gate.
    # Report the richest available partial evidence (by execution_count) --
    # ties resolve toward the more specific tier, since `ordered` is
    # already hierarchy-priority-sorted and `max` returns the first
    # maximum it finds.
    richest = max(ordered, key=lambda pair: pair[1].metrics.execution_count)
    if richest[1].metrics.execution_count > 0:
        return _TierEvidence(tier=richest[0], bucket=richest[1], sufficient=False)
    return _TierEvidence(tier="none", bucket=None, sufficient=False)


def _capability_component(
    passport: LearningPassport, capability: AgentCapability | None
) -> tuple[float, bool]:
    """`(component, used)`. `used=True` only when `capability` was
    requested and a sufficiently-sampled capability bucket exists for it --
    the only case that adds `CAPABILITY_VERIFIED_HISTORY` to the reason
    codes. Neutral (`0.5`, `used=False`) otherwise, so an absent or
    thinly-sampled capability bucket never helps or hurts the score."""
    if capability is None:
        return 0.5, False
    bucket = passport.capability_buckets.get(capability.value)
    if bucket is None:
        return 0.5, False
    if bucket.verification.verification_sample_count < MIN_SAMPLE_SIZE_FOR_CONFIDENCE:
        return 0.5, False
    rate = bucket.verification.verified_success_rate
    if rate is None:
        return 0.5, False
    return rate, True


def _insufficient_evidence_summary(agent_type: str, tier: _TierEvidence) -> str:
    if tier.bucket is None or tier.bucket.metrics.execution_count == 0:
        return f"'{agent_type}' has no observed execution evidence."
    verified = tier.bucket.verification.verification_sample_count
    return (
        f"'{agent_type}' has only {verified} verified sample(s) "
        f"({_TIER_PHRASES.get(tier.tier, tier.tier)}), below the minimum of "
        f"{MIN_SAMPLE_SIZE_FOR_CONFIDENCE} required to make a recommendation claim."
    )


def _evidence_summary(
    agent_type: str, tier: str, bucket: LearningBucket, outcome: RecommendationOutcome
) -> str:
    rate_pct = round((bucket.verification.verified_success_rate or 0.0) * 100)
    verb = (
        "is recommended"
        if outcome is RecommendationOutcome.RECOMMEND
        else "should be avoided if possible"
    )
    return (
        f"'{agent_type}' {verb} because it has {bucket.verification.verification_sample_count} "
        f"verified sample(s) with {rate_pct}% verified success {_TIER_PHRASES.get(tier, tier)}."
    )


class LearningPolicy:
    """Turns `LearningPassport`s into a `LearningRecommendation` for one
    task type (optionally scoped to a repository/capability). Stateless
    beyond its configured `RecommendationWeights` -- every call to
    `recommend` is a pure function of its arguments."""

    def __init__(self, *, weights: RecommendationWeights | None = None) -> None:
        self._weights = weights or RecommendationWeights()

    def recommend(
        self,
        passports: dict[str, LearningPassport],
        *,
        task_type: str,
        repository_id: str | None = None,
        capability: AgentCapability | None = None,
        candidate_agent_types: Iterable[str] | None = None,
    ) -> LearningRecommendation:
        """Deterministically recommend among `candidate_agent_types` (or,
        if omitted, every agent type present in `passports`) for
        `task_type`. Same `passports`/arguments always produce an
        identical semantic `LearningRecommendation`, regardless of
        `passports`'/`candidate_agent_types`' iteration order -- every
        agent's evidence is looked up independently, and results are
        always emitted in a fixed, documented sort order (score
        descending -- `None` last -- then `agent_type` ascending)."""
        if not task_type.strip():
            raise LearningEngineError("task_type must not be blank")

        agent_types = sorted(
            candidate_agent_types if candidate_agent_types is not None else passports.keys()
        )

        agent_recommendations = [
            self._recommend_one(
                passports.get(agent_type),
                agent_type,
                task_type=task_type,
                repository_id=repository_id,
                capability=capability,
            )
            for agent_type in agent_types
        ]
        ordered = tuple(
            sorted(
                agent_recommendations,
                key=lambda rec: (rec.score is None, -(rec.score or 0.0), rec.agent_type),
            )
        )

        recommended = tuple(
            rec.agent_type for rec in ordered if rec.outcome is RecommendationOutcome.RECOMMEND
        )
        avoid = tuple(
            rec.agent_type
            for rec in ordered
            if rec.outcome is RecommendationOutcome.AVOID_IF_POSSIBLE
        )
        insufficient = tuple(
            rec.agent_type
            for rec in ordered
            if rec.outcome
            in (RecommendationOutcome.INSUFFICIENT_EVIDENCE, RecommendationOutcome.NO_EVIDENCE)
        )

        return LearningRecommendation(
            task_type=task_type,
            repository_id=repository_id,
            capability=capability,
            agent_recommendations=ordered,
            recommended_agent_types=recommended,
            avoid_agent_types=avoid,
            insufficient_evidence_agent_types=insufficient,
        )

    def _recommend_one(
        self,
        passport: LearningPassport | None,
        agent_type: str,
        *,
        task_type: str,
        repository_id: str | None,
        capability: AgentCapability | None,
    ) -> AgentRecommendation:
        if passport is None or passport.passport.execution_count == 0:
            return AgentRecommendation(
                agent_type=agent_type,
                outcome=RecommendationOutcome.NO_EVIDENCE,
                tier_used="none",
                score=None,
                sample_count=0,
                verified_sample_count=0,
                verified_success_rate=None,
                reason_codes=(NO_VERIFIED_EVIDENCE,),
                evidence_summary=f"'{agent_type}' has no observed execution evidence.",
            )

        tier = _select_tier(passport, task_type=task_type, repository_id=repository_id)

        if not tier.sufficient:
            bucket = tier.bucket
            reason_codes: list[str] = [NO_VERIFIED_EVIDENCE]
            if bucket is not None and bucket.metrics.low_sample_size:
                reason_codes.append(LOW_SAMPLE_SIZE)
            return AgentRecommendation(
                agent_type=agent_type,
                outcome=RecommendationOutcome.INSUFFICIENT_EVIDENCE,
                tier_used=tier.tier,
                score=None,
                sample_count=bucket.metrics.execution_count if bucket else 0,
                verified_sample_count=(
                    bucket.verification.verification_sample_count if bucket else 0
                ),
                verified_success_rate=(
                    bucket.verification.verified_success_rate if bucket else None
                ),
                reason_codes=tuple(reason_codes),
                evidence_summary=_insufficient_evidence_summary(agent_type, tier),
            )

        bucket = tier.bucket
        assert bucket is not None  # `tier.sufficient` guarantees a bucket exists
        score, scored_reason_codes = self._score(bucket, passport, capability, tier.tier)
        verified_success_rate = bucket.verification.verified_success_rate
        assert verified_success_rate is not None  # guaranteed by the sample-count gate

        outcome = (
            RecommendationOutcome.RECOMMEND
            if verified_success_rate >= self._weights.avoid_threshold
            else RecommendationOutcome.AVOID_IF_POSSIBLE
        )

        return AgentRecommendation(
            agent_type=agent_type,
            outcome=outcome,
            tier_used=tier.tier,
            score=score,
            sample_count=bucket.metrics.execution_count,
            verified_sample_count=bucket.verification.verification_sample_count,
            verified_success_rate=verified_success_rate,
            reason_codes=scored_reason_codes,
            evidence_summary=_evidence_summary(agent_type, tier.tier, bucket, outcome),
        )

    def _score(
        self,
        bucket: LearningBucket,
        passport: LearningPassport,
        capability: AgentCapability | None,
        tier: str,
    ) -> tuple[float, tuple[str, ...]]:
        weights = self._weights
        verified_success_rate = bucket.verification.verified_success_rate
        assert verified_success_rate is not None

        reliability = execution_reliability(bucket.metrics)
        latency = latency_component(bucket.metrics.median_latency_ms, weights.target_latency_ms)
        capability_score, capability_used = _capability_component(passport, capability)

        base = (
            weights.verified_success_weight * verified_success_rate
            + weights.execution_reliability_weight * reliability
            + weights.latency_weight * latency
            + weights.capability_support_weight * capability_score
        )

        verification = bucket.verification
        verification_failure_rate = (
            verification.verification_failure_count / verification.verification_sample_count
            if verification.verification_sample_count > 0
            else 0.0
        )
        retry_rate = (
            passport.passport.retry_count / passport.passport.execution_count
            if passport.passport.execution_count > 0
            else 0.0
        )

        score = base
        score -= weights.verification_failure_penalty_strength * verification_failure_rate
        score -= weights.retry_penalty_strength * retry_rate
        score = max(0.0, min(1.0, score))

        reason_codes = list(_TIER_REASON_CODES.get(tier, ()))
        if bucket.metrics.low_sample_size:
            reason_codes.append(LOW_SAMPLE_SIZE)
        if verification_failure_rate > _VERIFICATION_FAILURE_HISTORY_THRESHOLD:
            reason_codes.append(VERIFICATION_FAILURE_HISTORY)
        if retry_rate > _RETRY_HISTORY_THRESHOLD:
            reason_codes.append(RETRY_HISTORY)
        if capability_used:
            reason_codes.append(CAPABILITY_VERIFIED_HISTORY)

        return score, tuple(reason_codes)


__all__ = ["LearningPolicy"]
