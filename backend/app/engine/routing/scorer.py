"""Deterministic, explainable eligibility filtering and scoring of one
candidate agent against one routing request.

Two distinct evidence treatments live here, deliberately different:

- **Hard constraints** (`eligibility_violation`) use *raw, unsmoothed*
  evidence. Missing evidence can never prove compliance with a hard
  constraint (`RoutingConstraints.minimum_reliability`/`max_latency_ms`/
  `max_cost_usd`) — a candidate with zero measurements is excluded, exactly
  like one that measurably fails the threshold. Assuming compliance from
  absence would silently let a constraint the caller depends on go
  unenforced.
- **Soft scoring** (`score_candidate`) uses *smoothed* evidence (see
  `_smoothed_reliability`) and always produces a definite factor score in
  `[0, 1]` — missing evidence gets an explicit neutral value (`0.5`), never
  `1.0` (that would reward having no track record) and never omitted (an
  omitted term would silently change what the composite score means from
  candidate to candidate).

Every score computed here is deterministic in its declared inputs alone —
no randomness, no timestamps, no I/O beyond the injected `evidence`
provider.
"""

from dataclasses import dataclass

from app.contracts.enums import AgentCapability, AgentStatus
from app.contracts.passports import AgentPassportMetricBucket
from app.contracts.routing import RoutingCandidateScore, RoutingRequest
from app.engine.routing.availability import CandidateAgent
from app.engine.routing.evidence import RoutingEvidenceProvider
from app.resilience.circuit_breaker import CircuitState

# Beta(1, 1) / Laplace "rule of succession" smoothing: posterior mean of a
# uniform prior over the true success rate after observing `successes` out
# of `executions` trials. Zero executions -> exactly 0.5 (neutral, not
# perfect). A single successful run (1/1) -> 2/3 ~= 0.667, comfortably below
# a well-evidenced 95/100 track record's ~0.941 -- one lucky run never
# outranks a proven one. Deliberately simple and documented, not a
# statistical model.
_RELIABILITY_PRIOR_SUCCESSES = 1.0
_RELIABILITY_PRIOR_STRENGTH = 2.0

_MIN_SAMPLE_SIZE_FOR_CONFIDENCE = 5
_NEUTRAL_SCORE = 0.5


@dataclass(frozen=True)
class RoutingWeights:
    """Explicit, configurable weights combining eight normalized per-factor
    scores (each in `[0, 1]`) into one composite score, also in `[0, 1]`.

    Deviates from the illustrative weight table in the Stage 4B spec (which
    lists "availability/health" as a candidate factor but omits it from the
    worked example) by giving it an explicit weight: a `DEGRADED` runtime is
    real, useful evidence and deserves its own term rather than being
    silently folded into reliability. `capability` and `preference` are
    weighted down slightly to make room for it. `capability` in particular
    is already a hard eligibility gate — every candidate that reaches
    scoring satisfies 100% of required capabilities by definition — so as a
    *scoring* dimension it is constant today and mostly differentiates
    nothing; it stays as an explicit, separately weighted factor anyway so a
    future `preferred_capabilities` signal can populate it meaningfully
    without a scorer rewrite.
    """

    capability_weight: float = 0.15
    overall_reliability_weight: float = 0.20
    task_reliability_weight: float = 0.20
    repository_reliability_weight: float = 0.15
    latency_weight: float = 0.10
    cost_weight: float = 0.05
    availability_weight: float = 0.10
    preference_weight: float = 0.05
    target_latency_ms: float = 5000.0

    def __post_init__(self) -> None:
        weights = (
            self.capability_weight,
            self.overall_reliability_weight,
            self.task_reliability_weight,
            self.repository_reliability_weight,
            self.latency_weight,
            self.cost_weight,
            self.availability_weight,
            self.preference_weight,
        )
        if min(weights) < 0:
            raise ValueError("routing weights must not be negative")
        total = sum(weights)
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"routing weights must sum to 1.0, got {total}")
        if self.target_latency_ms <= 0:
            raise ValueError("target_latency_ms must be positive")


def _missing_capabilities(
    candidate: CandidateAgent, request: RoutingRequest
) -> list[AgentCapability]:
    return [
        capability
        for capability in request.required_capabilities
        if capability not in candidate.descriptor.capabilities
    ]


def _raw_success_rate(bucket: AgentPassportMetricBucket | None) -> tuple[float | None, int]:
    """Unsmoothed observed success rate, for hard-constraint checks only.
    `None` when there is zero evidence — a hard constraint must never treat
    missing evidence as compliant."""
    if bucket is None or bucket.execution_count == 0:
        return None, 0
    return bucket.success_count / bucket.execution_count, bucket.execution_count


def _smoothed_reliability(bucket: AgentPassportMetricBucket | None) -> tuple[float, int]:
    """Laplace/Beta(1,1)-smoothed success rate for scoring. See the module
    docstring's prior-smoothing note. Always returns a definite float."""
    executions = bucket.execution_count if bucket is not None else 0
    successes = bucket.success_count if bucket is not None else 0
    smoothed = (successes + _RELIABILITY_PRIOR_SUCCESSES) / (
        executions + _RELIABILITY_PRIOR_STRENGTH
    )
    return smoothed, executions


def _latency_score(bucket: AgentPassportMetricBucket | None, weights: RoutingWeights) -> float:
    latency = bucket.median_latency_ms if bucket is not None else None
    if latency is None or latency <= 0:
        return _NEUTRAL_SCORE
    return max(0.0, min(1.0, weights.target_latency_ms / latency))


def _cost_score(cost_usd: float | None, max_cost_usd: float | None) -> float:
    """Neutral whenever cost evidence or a cost reference point is missing —
    currently always neutral, since no `RoutingEvidenceProvider`
    implementation reports real cost data yet (see `evidence.py`)."""
    if cost_usd is None or max_cost_usd is None or max_cost_usd <= 0:
        return _NEUTRAL_SCORE
    return max(0.0, min(1.0, 1.0 - (cost_usd / max_cost_usd)))


def _availability_score(status: AgentStatus) -> float:
    if status is AgentStatus.AVAILABLE:
        return 1.0
    if status is AgentStatus.DEGRADED:
        return _NEUTRAL_SCORE
    # UNAVAILABLE/UNKNOWN are hard-excluded before scoring; unreachable here
    # for an eligible candidate, but a safe neutral default regardless.
    return _NEUTRAL_SCORE


def _capability_score() -> float:
    """Constant `1.0` for every candidate that reaches scoring — required
    capabilities are a hard eligibility gate (see `eligibility_violation`),
    so every scored candidate already satisfies them fully. Kept as an
    explicit weighted factor for future `preferred_capabilities` support;
    see `RoutingWeights`."""
    return 1.0


def _preference_score(agent_type: str, preferred_agent_types: list[str]) -> float:
    """`0.5` (neutral) when no preference was expressed at all; `1.0` for a
    preferred candidate; `0.0` for a non-preferred candidate when a
    preference list exists. Never affects eligibility — see
    `eligibility_violation`, which never inspects `preferred_agent_types`."""
    if not preferred_agent_types:
        return _NEUTRAL_SCORE
    return 1.0 if agent_type in preferred_agent_types else 0.0


def eligibility_violation(
    candidate: CandidateAgent,
    request: RoutingRequest,
    evidence: RoutingEvidenceProvider,
) -> str | None:
    """The first hard-eligibility violation found, or `None` if eligible.

    Checked in this fixed order, so identical inputs always report the same
    single reason:

    1. explicit exclusion (`constraints.excluded_agent_types`)
    2. missing required capability
    3. runtime not confirmed usable (`UNAVAILABLE`/`UNKNOWN` status)
    4. circuit breaker open
    5. `minimum_reliability` (missing evidence cannot prove compliance)
    6. `max_latency_ms` (missing evidence cannot prove compliance)
    7. `max_cost_usd` (missing evidence cannot prove compliance — no cost
       evidence source exists yet, so this always excludes when set)

    `runtime_kind` is never checked directly here: a required interaction
    -mode capability (`RAW_COMPLETION`/`STRUCTURED_OUTPUT`/`TOOL_CALLING`)
    already gates eligibility via ordinary capability matching (step 2) —
    `runtime_kind` itself carries no independent eligibility or quality
    weight (see `RoutingWeights` and `docs/contracts.md`).
    """
    agent_type = candidate.descriptor.agent_type
    constraints = request.constraints

    if agent_type in constraints.excluded_agent_types:
        return "excluded by routing constraints"

    missing = _missing_capabilities(candidate, request)
    if missing:
        return f"missing required capabilities: {', '.join(sorted(missing))}"

    if candidate.status in (AgentStatus.UNAVAILABLE, AgentStatus.UNKNOWN):
        return "agent unavailable"

    if candidate.circuit_state is CircuitState.OPEN:
        return "circuit breaker open"

    if constraints.minimum_reliability is not None:
        reliability, _ = _raw_success_rate(evidence.overall_metrics(agent_type))
        if reliability is None:
            return "no reliability evidence available to satisfy minimum_reliability"
        if reliability < constraints.minimum_reliability:
            return "reliability below minimum_reliability"

    if constraints.max_latency_ms is not None:
        overall = evidence.overall_metrics(agent_type)
        latency = overall.median_latency_ms if overall is not None else None
        if latency is None:
            return "no latency evidence available to satisfy max_latency_ms"
        if latency > constraints.max_latency_ms:
            return "latency exceeds max_latency_ms"

    if constraints.max_cost_usd is not None:
        cost = evidence.cost_usd_estimate(agent_type)
        if cost is None:
            return "no cost evidence available to satisfy max_cost_usd"
        if cost > constraints.max_cost_usd:
            return "cost exceeds max_cost_usd"

    return None


def score_candidate(
    candidate: CandidateAgent,
    request: RoutingRequest,
    evidence: RoutingEvidenceProvider,
    weights: RoutingWeights,
) -> RoutingCandidateScore:
    """Evaluate one candidate. Deterministic for the same four inputs."""
    agent_type = candidate.descriptor.agent_type
    violation = eligibility_violation(candidate, request, evidence)
    eligible = violation is None
    capability_ok = not _missing_capabilities(candidate, request)

    overall = evidence.overall_metrics(agent_type)
    task_bucket = evidence.task_type_metrics(agent_type, request.task_type)
    repository_id = request.repository.repository_id if request.repository else None
    repository_bucket = (
        evidence.repository_metrics(agent_type, repository_id) if repository_id else None
    )

    overall_reliability, overall_n = _smoothed_reliability(overall)
    task_reliability, task_n = _smoothed_reliability(task_bucket)
    repository_reliability, repository_n = _smoothed_reliability(repository_bucket)
    latency_score = _latency_score(overall, weights)
    cost_score = _cost_score(
        evidence.cost_usd_estimate(agent_type), request.constraints.max_cost_usd
    )
    availability_score = _availability_score(candidate.status)
    capability_score = _capability_score()
    preference_score = _preference_score(agent_type, request.constraints.preferred_agent_types)

    composite_score = (
        weights.capability_weight * capability_score
        + weights.overall_reliability_weight * overall_reliability
        + weights.task_reliability_weight * task_reliability
        + weights.repository_reliability_weight * repository_reliability
        + weights.latency_weight * latency_score
        + weights.cost_weight * cost_score
        + weights.availability_weight * availability_score
        + weights.preference_weight * preference_score
    )
    composite_score = max(0.0, min(1.0, composite_score))

    sample_size = max(overall_n, task_n, repository_n)
    low_sample_size = sample_size < _MIN_SAMPLE_SIZE_FOR_CONFIDENCE

    return RoutingCandidateScore(
        agent_type=agent_type,
        eligible=eligible,
        excluded_reason=violation,
        capability_match=capability_ok,
        reliability_score=overall_reliability,
        latency_score=latency_score,
        cost_score=cost_score,
        repository_score=repository_reliability,
        task_type_score=task_reliability,
        composite_score=composite_score,
        sample_size=sample_size,
        low_sample_size=low_sample_size,
        # Deterministic factor-level breakdown, preserved for Stage 4C's
        # Explainability Engine (ScoreContribution/EvidenceItem) to consume
        # without recomputation — see docs/contracts.md.
        evidence={
            "overall_execution_count": overall_n,
            "task_type_execution_count": task_n,
            "repository_execution_count": repository_n,
            "factor_scores": {
                "capability": capability_score,
                "overall_reliability": overall_reliability,
                "task_reliability": task_reliability,
                "repository_reliability": repository_reliability,
                "latency": latency_score,
                "cost": cost_score,
                "availability": availability_score,
                "preference": preference_score,
            },
            "factor_weights": {
                "capability": weights.capability_weight,
                "overall_reliability": weights.overall_reliability_weight,
                "task_reliability": weights.task_reliability_weight,
                "repository_reliability": weights.repository_reliability_weight,
                "latency": weights.latency_weight,
                "cost": weights.cost_weight,
                "availability": weights.availability_weight,
                "preference": weights.preference_weight,
            },
        },
    )


def manual_override_safety_violation(
    candidate: CandidateAgent, request: RoutingRequest
) -> str | None:
    """Hard operational-safety checks a manual override must still satisfy,
    independent of the request's soft/policy constraints (see
    `router.py`'s manual-override handling for exactly what is and is not
    overridable)."""
    if candidate.status in (AgentStatus.UNAVAILABLE, AgentStatus.UNKNOWN):
        return "agent unavailable"
    if candidate.circuit_state is CircuitState.OPEN:
        return "circuit breaker open"
    missing = _missing_capabilities(candidate, request)
    if missing:
        return f"missing required capabilities: {', '.join(sorted(missing))}"
    return None


__all__ = [
    "RoutingWeights",
    "eligibility_violation",
    "manual_override_safety_violation",
    "score_candidate",
]
