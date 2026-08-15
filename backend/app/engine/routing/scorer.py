"""Deterministic, explainable eligibility filtering and scoring of one
candidate agent against one routing request.

Two distinct evidence treatments live here, deliberately different:

- **Hard constraints** (`eligibility_violation`) use *raw, unsmoothed*
  evidence. Missing evidence can never prove compliance with a hard
  constraint (`RoutingConstraints.minimum_reliability`/`max_latency_ms`/
  `max_cost_usd`) — a candidate with zero measurements is excluded, exactly
  like one that measurably fails the threshold. Assuming compliance from
  absence would silently let a constraint the caller depends on go
  unenforced. **Invalid** evidence (non-finite or negative — see
  `_validate_finite_nonnegative`) is treated the same way: never as
  compliant, never as zero, and reported with a distinct reason from
  "unavailable" so the difference between "nothing was measured" and
  "something was measured but it was garbage" stays visible.
- **Soft scoring** (`score_candidate`) uses *smoothed* evidence (see
  `_smoothed_reliability`) and always produces a definite factor score in
  `[0, 1]` — missing or invalid evidence both get an explicit neutral value
  (`0.5`), never `1.0` (that would reward having no track record, or
  reward garbage data even more perversely) and never omitted (an omitted
  term would silently change what the composite score means from candidate
  to candidate). Every numeric factor is validated with `math.isfinite`
  *before* any `min`/`max` clamping — `max(0.0, min(1.0, float("nan")))`
  silently evaluates to `1.0` in Python (a `min`/`max`-with-NaN artifact,
  not a deliberate choice), so checking finiteness first is load-bearing,
  not a style preference.

Every score computed here is deterministic in its declared inputs alone —
no randomness, no timestamps, no I/O beyond the injected `evidence`
provider.
"""

import math
from dataclasses import dataclass

from app.contracts.enums import AgentStatus
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

# Stable, machine-readable exclusion reason codes (Stage 4C-ready), paired
# with the existing safe, human-readable message on every
# `EligibilityViolation`/`RoutingCandidateScore.excluded_reason`.
EXPLICITLY_EXCLUDED = "explicitly_excluded"
MISSING_CAPABILITY = "missing_capability"
RUNTIME_UNAVAILABLE = "runtime_unavailable"
CIRCUIT_OPEN = "circuit_open"
RELIABILITY_EVIDENCE_UNAVAILABLE = "reliability_evidence_unavailable"
RELIABILITY_BELOW_THRESHOLD = "reliability_below_threshold"
LATENCY_EVIDENCE_UNAVAILABLE = "latency_evidence_unavailable"
LATENCY_EVIDENCE_INVALID = "latency_evidence_invalid"
LATENCY_ABOVE_THRESHOLD = "latency_above_threshold"
COST_EVIDENCE_UNAVAILABLE = "cost_evidence_unavailable"
COST_EVIDENCE_INVALID = "cost_evidence_invalid"
COST_ABOVE_THRESHOLD = "cost_above_threshold"


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
    scoring satisfies 100% of its effective required capabilities by
    definition — so as a *scoring* dimension it is constant today and
    mostly differentiates nothing; it stays as an explicit, separately
    weighted factor anyway so a future `preferred_capabilities` signal can
    populate it meaningfully without a scorer rewrite.
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


@dataclass(frozen=True)
class EligibilityViolation:
    """A hard-eligibility failure: a stable machine-readable `code` (one of
    the module-level `*_UNAVAILABLE`/`*_INVALID`/`*_THRESHOLD`/etc.
    constants) paired with the existing safe, human-readable `message`."""

    code: str
    message: str


def _validate_finite_nonnegative(value: float | None) -> tuple[float | None, bool]:
    """Returns `(value, was_invalid)`. `was_invalid=True` means a value was
    present but rejected (NaN, +-infinity, or negative) — distinct from
    `value is None` (no evidence was ever offered). Used for evidence
    sourced from a bare `RoutingEvidenceProvider` return value (e.g.
    `cost_usd_estimate`), which — unlike `AgentPassportMetricBucket` fields —
    is never validated by Pydantic at runtime, since `RoutingEvidenceProvider`
    is a `Protocol`, not an enforced base class.
    """
    if value is None:
        return None, False
    if not math.isfinite(value) or value < 0:
        return None, True
    return value, False


def _effective_required_capabilities(request: RoutingRequest) -> list[str]:
    """The full hard-required capability set: `RoutingRequest.required_capabilities`
    (typically `TaskSpec`-derived) unioned with `RoutingConstraints.required_capabilities`
    (additional caller/policy-required capabilities), in that declaration
    order, deduplicated by value. `AgentCapability` is a `StrEnum`, so its
    members and `RoutingConstraints.required_capabilities`'s plain strings
    compare equal by value — no enum coercion (and no risk of raising on an
    unrecognized string) is needed to unify them."""
    effective: list[str] = []
    seen: set[str] = set()
    for capability in (*request.required_capabilities, *request.constraints.required_capabilities):
        value = str(capability)
        if value not in seen:
            seen.add(value)
            effective.append(value)
    return effective


def _missing_capabilities(candidate: CandidateAgent, request: RoutingRequest) -> list[str]:
    declared = {str(capability) for capability in candidate.descriptor.capabilities}
    return [
        capability
        for capability in _effective_required_capabilities(request)
        if capability not in declared
    ]


def _raw_success_rate(bucket: AgentPassportMetricBucket | None) -> tuple[float | None, int]:
    """Unsmoothed observed success rate, for hard-constraint checks only.
    `None` when there is zero evidence — a hard constraint must never treat
    missing evidence as compliant. `AgentPassportMetricBucket` already
    guarantees `0 <= success_count <= execution_count` at construction, so
    the rate is always in `[0, 1]`; the `isfinite` check is defense in depth
    against a duck-typed, non-Pydantic-validated evidence object."""
    if bucket is None or bucket.execution_count == 0:
        return None, 0
    rate = bucket.success_count / bucket.execution_count
    if not math.isfinite(rate):
        return None, 0
    return rate, bucket.execution_count


def _smoothed_reliability(bucket: AgentPassportMetricBucket | None) -> tuple[float, int, int]:
    """Laplace/Beta(1,1)-smoothed success rate for scoring, plus the raw
    `(executions, successes)` pair for evidence preservation (see
    `score_candidate`). Always returns a definite, `[0, 1]`-bounded float —
    defensively guaranteed here even though `AgentPassportMetricBucket`
    should already prevent malformed counts, in case a future evidence
    provider hands back a duck-typed object that skips Pydantic validation.
    """
    executions = bucket.execution_count if bucket is not None else 0
    successes = bucket.success_count if bucket is not None else 0
    if executions < 0 or successes < 0 or successes > executions:
        return _NEUTRAL_SCORE, 0, 0
    smoothed = (successes + _RELIABILITY_PRIOR_SUCCESSES) / (
        executions + _RELIABILITY_PRIOR_STRENGTH
    )
    if not math.isfinite(smoothed):
        return _NEUTRAL_SCORE, 0, 0
    return max(0.0, min(1.0, smoothed)), executions, successes


def _latency_score(latency: float | None, weights: RoutingWeights) -> float:
    """`latency` must already be validated by the caller (see
    `_validate_finite_nonnegative`) — `None` covers both "no evidence" and
    "invalid evidence," both neutral here."""
    if latency is None or latency <= 0:
        return _NEUTRAL_SCORE
    score = weights.target_latency_ms / latency
    if not math.isfinite(score):
        return _NEUTRAL_SCORE
    return max(0.0, min(1.0, score))


def _cost_score(cost_usd: float | None, max_cost_usd: float | None) -> float:
    """`cost_usd` must already be validated by the caller (see
    `_validate_finite_nonnegative`). Neutral whenever cost evidence or a
    finite, positive cost reference point is missing — currently always
    neutral in practice, since no `RoutingEvidenceProvider` implementation
    reports real cost data yet (see `evidence.py`)."""
    if (
        cost_usd is None
        or max_cost_usd is None
        or not math.isfinite(max_cost_usd)
        or max_cost_usd <= 0
    ):
        return _NEUTRAL_SCORE
    score = 1.0 - (cost_usd / max_cost_usd)
    if not math.isfinite(score):
        return _NEUTRAL_SCORE
    return max(0.0, min(1.0, score))


def _availability_score(status: AgentStatus) -> float:
    if status is AgentStatus.AVAILABLE:
        return 1.0
    if status is AgentStatus.DEGRADED:
        return _NEUTRAL_SCORE
    # UNAVAILABLE/UNKNOWN are hard-excluded before scoring; unreachable here
    # for an eligible candidate, but a safe neutral default regardless.
    return _NEUTRAL_SCORE


def _capability_score() -> float:
    """Constant `1.0` for every candidate that reaches scoring — the
    effective required capabilities are a hard eligibility gate (see
    `eligibility_violation`), so every scored candidate already satisfies
    them fully. Kept as an explicit weighted factor for future
    `preferred_capabilities` support; see `RoutingWeights`."""
    return 1.0


def _preference_score(agent_type: str, preferred_agent_types: list[str]) -> float:
    """`0.5` (neutral) when no preference was expressed at all; `1.0` for a
    preferred candidate; `0.0` for a non-preferred candidate when a
    preference list exists. Never affects eligibility — see
    `eligibility_violation`, which never inspects `preferred_agent_types`."""
    if not preferred_agent_types:
        return _NEUTRAL_SCORE
    return 1.0 if agent_type in preferred_agent_types else 0.0


def _eligibility_violation_detail(
    candidate: CandidateAgent,
    request: RoutingRequest,
    evidence: RoutingEvidenceProvider,
) -> EligibilityViolation | None:
    """The first hard-eligibility violation found, or `None` if eligible.

    Checked in this fixed order, so identical inputs always report the same
    single reason:

    1. explicit exclusion (`constraints.excluded_agent_types`)
    2. missing an effective required capability (`_effective_required_capabilities`)
    3. runtime not confirmed usable (`UNAVAILABLE`/`UNKNOWN` status)
    4. circuit breaker open
    5. `minimum_reliability` (missing evidence cannot prove compliance)
    6. `max_latency_ms` (missing OR invalid evidence cannot prove compliance)
    7. `max_cost_usd` (missing OR invalid evidence cannot prove compliance —
       no cost evidence source exists yet, so this always excludes when set)

    This is also the exact check a manual override target must still pass
    (see `router.py`'s `_route_manual_override`) — a manual override bypasses
    automatic *ranking*, never a hard safety/policy constraint.

    `runtime_kind` is never checked directly here: a required interaction
    -mode capability (`RAW_COMPLETION`/`STRUCTURED_OUTPUT`/`TOOL_CALLING`)
    already gates eligibility via ordinary capability matching (step 2) —
    `runtime_kind` itself carries no independent eligibility or quality
    weight (see `RoutingWeights` and `docs/contracts.md`).
    """
    agent_type = candidate.descriptor.agent_type
    constraints = request.constraints

    if agent_type in constraints.excluded_agent_types:
        return EligibilityViolation(EXPLICITLY_EXCLUDED, "excluded by routing constraints")

    missing = _missing_capabilities(candidate, request)
    if missing:
        return EligibilityViolation(
            MISSING_CAPABILITY, f"missing required capabilities: {', '.join(sorted(missing))}"
        )

    if candidate.status in (AgentStatus.UNAVAILABLE, AgentStatus.UNKNOWN):
        return EligibilityViolation(RUNTIME_UNAVAILABLE, "agent unavailable")

    if candidate.circuit_state is CircuitState.OPEN:
        return EligibilityViolation(CIRCUIT_OPEN, "circuit breaker open")

    if constraints.minimum_reliability is not None:
        reliability, _ = _raw_success_rate(evidence.overall_metrics(agent_type))
        if reliability is None:
            return EligibilityViolation(
                RELIABILITY_EVIDENCE_UNAVAILABLE,
                "no reliability evidence available to satisfy minimum_reliability",
            )
        if reliability < constraints.minimum_reliability:
            return EligibilityViolation(
                RELIABILITY_BELOW_THRESHOLD, "reliability below minimum_reliability"
            )

    if constraints.max_latency_ms is not None:
        overall = evidence.overall_metrics(agent_type)
        raw_latency = overall.median_latency_ms if overall is not None else None
        latency, invalid = _validate_finite_nonnegative(raw_latency)
        if invalid:
            return EligibilityViolation(
                LATENCY_EVIDENCE_INVALID,
                "latency evidence is invalid and cannot satisfy max_latency_ms",
            )
        if latency is None:
            return EligibilityViolation(
                LATENCY_EVIDENCE_UNAVAILABLE,
                "no latency evidence available to satisfy max_latency_ms",
            )
        if latency > constraints.max_latency_ms:
            return EligibilityViolation(LATENCY_ABOVE_THRESHOLD, "latency exceeds max_latency_ms")

    if constraints.max_cost_usd is not None:
        raw_cost = evidence.cost_usd_estimate(agent_type)
        cost, invalid = _validate_finite_nonnegative(raw_cost)
        if invalid:
            return EligibilityViolation(
                COST_EVIDENCE_INVALID, "cost evidence is invalid and cannot satisfy max_cost_usd"
            )
        if cost is None:
            return EligibilityViolation(
                COST_EVIDENCE_UNAVAILABLE, "no cost evidence available to satisfy max_cost_usd"
            )
        if cost > constraints.max_cost_usd:
            return EligibilityViolation(COST_ABOVE_THRESHOLD, "cost exceeds max_cost_usd")

    return None


def eligibility_violation(
    candidate: CandidateAgent,
    request: RoutingRequest,
    evidence: RoutingEvidenceProvider,
) -> str | None:
    """The human-readable message from `_eligibility_violation_detail`, or
    `None` if eligible. See that function for the exact check order and the
    paired machine-readable `EligibilityViolation.code`."""
    detail = _eligibility_violation_detail(candidate, request, evidence)
    return detail.message if detail is not None else None


def score_candidate(
    candidate: CandidateAgent,
    request: RoutingRequest,
    evidence: RoutingEvidenceProvider,
    weights: RoutingWeights,
) -> RoutingCandidateScore:
    """Evaluate one candidate. Deterministic for the same four inputs."""
    agent_type = candidate.descriptor.agent_type
    violation = _eligibility_violation_detail(candidate, request, evidence)
    eligible = violation is None
    missing = _missing_capabilities(candidate, request)
    capability_ok = not missing

    overall = evidence.overall_metrics(agent_type)
    task_bucket = evidence.task_type_metrics(agent_type, request.task_type)
    repository_id = request.repository.repository_id if request.repository else None
    repository_bucket = (
        evidence.repository_metrics(agent_type, repository_id) if repository_id else None
    )

    overall_reliability, overall_n, overall_successes = _smoothed_reliability(overall)
    task_reliability, task_n, task_successes = _smoothed_reliability(task_bucket)
    repository_reliability, repository_n, repository_successes = _smoothed_reliability(
        repository_bucket
    )

    raw_latency, _ = _validate_finite_nonnegative(
        overall.median_latency_ms if overall is not None else None
    )
    latency_score = _latency_score(raw_latency, weights)

    raw_cost, _ = _validate_finite_nonnegative(evidence.cost_usd_estimate(agent_type))
    cost_score = _cost_score(raw_cost, request.constraints.max_cost_usd)

    availability_score = _availability_score(candidate.status)
    capability_score = _capability_score()
    preferred_agent_types = request.constraints.preferred_agent_types
    preference_score = _preference_score(agent_type, preferred_agent_types)

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
        excluded_reason=violation.message if violation is not None else None,
        capability_match=capability_ok,
        reliability_score=overall_reliability,
        latency_score=latency_score,
        cost_score=cost_score,
        repository_score=repository_reliability,
        task_type_score=task_reliability,
        composite_score=composite_score,
        sample_size=sample_size,
        low_sample_size=low_sample_size,
        # Deterministic, raw evidence snapshot AND factor-level breakdown,
        # preserved exactly as used for this decision — preserved for
        # Stage 4C's Explainability Engine (ScoreContribution/EvidenceItem)
        # to consume without re-querying the (possibly mutable/stale-by-then)
        # evidence provider. See docs/contracts.md.
        evidence={
            "overall": {
                "execution_count": overall_n,
                "success_count": overall_successes,
                "smoothed_reliability": overall_reliability,
            },
            "task_specific": {
                "execution_count": task_n,
                "success_count": task_successes,
                "smoothed_reliability": task_reliability,
            },
            "repository_specific": {
                "execution_count": repository_n,
                "success_count": repository_successes,
                "smoothed_reliability": repository_reliability,
            },
            "latency": {
                "raw_median_latency_ms": raw_latency,
                "score": latency_score,
            },
            "cost": {
                "raw_cost_usd": raw_cost,
                "score": cost_score,
            },
            "availability": {
                "status": candidate.status.value,
                "circuit_state": candidate.circuit_state.value,
            },
            "preference": {
                "preferred": agent_type in preferred_agent_types,
            },
            "capabilities": {
                "required": _effective_required_capabilities(request),
                "declared": [str(c) for c in candidate.descriptor.capabilities],
                "missing": missing,
            },
            "constraints": {
                "minimum_reliability": request.constraints.minimum_reliability,
                "max_latency_ms": request.constraints.max_latency_ms,
                "max_cost_usd": request.constraints.max_cost_usd,
            },
            "exclusion_reason_code": violation.code if violation is not None else None,
            # True when nothing in `overall`/`task_specific`/`repository_specific`
            # had any recorded executions -- i.e. this candidate's composite
            # score reflects no differentiating historical evidence at all.
            # See `explanation.py`'s bootstrap-aware wording.
            "bootstrap_no_differentiating_evidence": sample_size == 0,
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


__all__ = [
    "COST_ABOVE_THRESHOLD",
    "COST_EVIDENCE_INVALID",
    "COST_EVIDENCE_UNAVAILABLE",
    "CIRCUIT_OPEN",
    "EXPLICITLY_EXCLUDED",
    "LATENCY_ABOVE_THRESHOLD",
    "LATENCY_EVIDENCE_INVALID",
    "LATENCY_EVIDENCE_UNAVAILABLE",
    "MISSING_CAPABILITY",
    "RELIABILITY_BELOW_THRESHOLD",
    "RELIABILITY_EVIDENCE_UNAVAILABLE",
    "RUNTIME_UNAVAILABLE",
    "EligibilityViolation",
    "RoutingWeights",
    "eligibility_violation",
    "score_candidate",
]
