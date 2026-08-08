"""Core Stage 4C building blocks: turning one already-produced `RoutingDecision`
snapshot into `ScoreContribution`/`EvidenceItem`/`ExclusionReason` values, a
deterministic decision identity, and whole-snapshot consistency validation.

**Source of truth, load-bearing:** every function here reads only
`RoutingDecision`/`RoutingCandidateScore`/`RoutingCandidateScore.evidence` —
the exact snapshot Stage 4B already produced. Nothing here re-queries
`RoutingEvidenceProvider`, `AgentPassport`, availability services,
`CircuitBreaker`, or any other live provider state; a decision explained
today and a decision explained a year from now (from the same stored
`RoutingDecision`) must produce logically identical output.

`app.engine.routing.scorer` is imported only for its stable, machine-readable
exclusion-reason-code *string constants* (`MISSING_CAPABILITY`, etc.) and the
documented shape of `RoutingCandidateScore.evidence` it produces — a
compile-time dependency on constant strings, never a runtime call into the
scorer or any evidence provider.
"""

import hashlib
import json
import math
from typing import Any

from pydantic import BaseModel, ValidationError

from app.contracts.explainability import EvidenceItem, ExclusionReason, ScoreContribution
from app.contracts.routing import RoutingCandidateScore, RoutingDecision
from app.engine.routing.scorer import (
    CIRCUIT_OPEN,
    COST_ABOVE_THRESHOLD,
    COST_EVIDENCE_INVALID,
    COST_EVIDENCE_UNAVAILABLE,
    EXPLICITLY_EXCLUDED,
    LATENCY_ABOVE_THRESHOLD,
    LATENCY_EVIDENCE_INVALID,
    LATENCY_EVIDENCE_UNAVAILABLE,
    MISSING_CAPABILITY,
    RELIABILITY_BELOW_THRESHOLD,
    RELIABILITY_EVIDENCE_UNAVAILABLE,
    RUNTIME_UNAVAILABLE,
)


class ExplainabilityDataError(ValueError):
    """Raised when a `RoutingDecision`/`RoutingCandidateScore` snapshot is
    malformed or internally contradictory: a factor-key mismatch, a
    non-finite or out-of-range score, a missing raw-evidence field, an
    excluded candidate with no exclusion code, an eligible candidate with a
    contradictory exclusion code, or a selected candidate that is missing or
    ineligible.

    The explainability engine never silently repairs or fabricates missing
    data to make a bad snapshot look consistent — it always fails loudly
    with this typed error instead.
    """


# The eight scoring factors `app.engine.routing.scorer.score_candidate`
# always populates in `evidence["factor_scores"]`/`evidence["factor_weights"]`.
# Fixed tuple (not derived from a dict's insertion order) so factor ordering
# in every `ScoreContribution` list is deterministic and documented here,
# independent of how the scorer happens to build its dict.
FACTOR_ORDER: tuple[str, ...] = (
    "capability",
    "overall_reliability",
    "task_reliability",
    "repository_reliability",
    "latency",
    "cost",
    "availability",
    "preference",
)
_FACTOR_SET = frozenset(FACTOR_ORDER)

# Short, safe, human-readable phrases for each stable exclusion reason code —
# shared by `counterfactuals.py` and `formatter.py` so the wording is defined
# in exactly one place.
EXCLUSION_REASON_PHRASES: dict[str, str] = {
    EXPLICITLY_EXCLUDED: "was explicitly excluded by routing constraints",
    MISSING_CAPABILITY: "lacked a required capability",
    RUNTIME_UNAVAILABLE: "was unavailable",
    CIRCUIT_OPEN: "had an open circuit breaker",
    RELIABILITY_EVIDENCE_UNAVAILABLE: "had no reliability evidence available",
    RELIABILITY_BELOW_THRESHOLD: "had reliability below the configured minimum",
    LATENCY_EVIDENCE_UNAVAILABLE: "had no latency evidence available",
    LATENCY_EVIDENCE_INVALID: "had invalid latency evidence",
    LATENCY_ABOVE_THRESHOLD: "exceeded the configured latency limit",
    COST_EVIDENCE_UNAVAILABLE: "had no cost evidence available",
    COST_EVIDENCE_INVALID: "had invalid cost evidence",
    COST_ABOVE_THRESHOLD: "exceeded the configured cost limit",
}

def safe_construct[ModelT: BaseModel](model_cls: type[ModelT], **kwargs: Any) -> ModelT:
    """Construct a contract model, translating any `pydantic.ValidationError`
    into the engine's own typed `ExplainabilityDataError` — callers of the
    explainability engine see one consistent error type for every kind of
    malformed input, whether the problem was caught by this module's own
    checks or by a contract's own field validators (e.g. the
    reasoning-shaped-key rejection on `EvidenceItem.value`)."""
    try:
        return model_cls(**kwargs)
    except ValidationError as exc:
        raise ExplainabilityDataError(f"invalid {model_cls.__name__}: {exc}") from exc


def _require(evidence: dict[str, Any], key: str, agent_type: str) -> Any:
    if key not in evidence:
        raise ExplainabilityDataError(
            f"candidate '{agent_type}' evidence is missing required key '{key}'"
        )
    return evidence[key]


def _require_mapping(evidence: dict[str, Any], key: str, agent_type: str) -> dict[str, Any]:
    value = _require(evidence, key, agent_type)
    if not isinstance(value, dict):
        raise ExplainabilityDataError(
            f"candidate '{agent_type}' evidence key '{key}' must be an object, "
            f"got {type(value).__name__}"
        )
    return value


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _require_unit_interval(
    mapping: dict[str, Any], key: str, agent_type: str, context: str
) -> float:
    if key not in mapping:
        raise ExplainabilityDataError(
            f"candidate '{agent_type}' {context} is missing required key '{key}'"
        )
    value = mapping[key]
    if not _is_finite_number(value):
        raise ExplainabilityDataError(
            f"candidate '{agent_type}' {context}.{key} must be a finite number, got {value!r}"
        )
    if not 0.0 <= float(value) <= 1.0:
        raise ExplainabilityDataError(
            f"candidate '{agent_type}' {context}.{key} must be between 0.0 and 1.0, got {value!r}"
        )
    return float(value)


def _require_nonnegative_int(
    mapping: dict[str, Any], key: str, agent_type: str, context: str
) -> int:
    if key not in mapping:
        raise ExplainabilityDataError(
            f"candidate '{agent_type}' {context} is missing required key '{key}'"
        )
    value = mapping[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ExplainabilityDataError(
            f"candidate '{agent_type}' {context}.{key} must be a non-negative integer, "
            f"got {value!r}"
        )
    return value


def _validate_reliability_bucket(evidence: dict[str, Any], key: str, agent_type: str) -> None:
    bucket = _require_mapping(evidence, key, agent_type)
    _require_nonnegative_int(bucket, "execution_count", agent_type, key)
    _require_nonnegative_int(bucket, "success_count", agent_type, key)
    _require_unit_interval(bucket, "smoothed_reliability", agent_type, key)


def _validate_evidence_shape(score: RoutingCandidateScore) -> None:
    """Validate the exact raw-evidence/factor-breakdown shape
    `app.engine.routing.scorer.score_candidate` always produces. Raises
    `ExplainabilityDataError` on any missing key, non-finite value, or
    out-of-range value — never fabricates a missing factor."""
    agent_type = score.agent_type
    evidence = score.evidence
    if not isinstance(evidence, dict):
        raise ExplainabilityDataError(f"candidate '{agent_type}' evidence must be an object")

    for key in ("overall", "task_specific", "repository_specific"):
        _validate_reliability_bucket(evidence, key, agent_type)

    latency = _require_mapping(evidence, "latency", agent_type)
    if "raw_median_latency_ms" not in latency:
        raise ExplainabilityDataError(
            f"candidate '{agent_type}' latency is missing 'raw_median_latency_ms'"
        )
    raw_latency = latency["raw_median_latency_ms"]
    if raw_latency is not None and not _is_finite_number(raw_latency):
        raise ExplainabilityDataError(
            f"candidate '{agent_type}' latency.raw_median_latency_ms is invalid"
        )
    _require_unit_interval(latency, "score", agent_type, "latency")

    cost = _require_mapping(evidence, "cost", agent_type)
    if "raw_cost_usd" not in cost:
        raise ExplainabilityDataError(f"candidate '{agent_type}' cost is missing 'raw_cost_usd'")
    raw_cost = cost["raw_cost_usd"]
    if raw_cost is not None and not _is_finite_number(raw_cost):
        raise ExplainabilityDataError(f"candidate '{agent_type}' cost.raw_cost_usd is invalid")
    _require_unit_interval(cost, "score", agent_type, "cost")

    availability = _require_mapping(evidence, "availability", agent_type)
    for key in ("status", "circuit_state"):
        value = availability.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ExplainabilityDataError(
                f"candidate '{agent_type}' availability.{key} must be a non-blank string"
            )

    preference = _require_mapping(evidence, "preference", agent_type)
    if not isinstance(preference.get("preferred"), bool):
        raise ExplainabilityDataError(
            f"candidate '{agent_type}' preference.preferred must be a boolean"
        )

    capabilities = _require_mapping(evidence, "capabilities", agent_type)
    for key in ("required", "declared", "missing"):
        value = capabilities.get(key)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ExplainabilityDataError(
                f"candidate '{agent_type}' capabilities.{key} must be a list of strings"
            )

    constraints = _require_mapping(evidence, "constraints", agent_type)
    for key in ("minimum_reliability", "max_latency_ms", "max_cost_usd"):
        if key not in constraints:
            raise ExplainabilityDataError(
                f"candidate '{agent_type}' constraints is missing '{key}'"
            )
        value = constraints[key]
        if value is not None and not _is_finite_number(value):
            raise ExplainabilityDataError(f"candidate '{agent_type}' constraints.{key} is invalid")

    if "exclusion_reason_code" not in evidence:
        raise ExplainabilityDataError(
            f"candidate '{agent_type}' evidence is missing 'exclusion_reason_code'"
        )

    if "bootstrap_no_differentiating_evidence" not in evidence or not isinstance(
        evidence["bootstrap_no_differentiating_evidence"], bool
    ):
        raise ExplainabilityDataError(
            f"candidate '{agent_type}' evidence.bootstrap_no_differentiating_evidence "
            "must be a boolean"
        )

    factor_scores = _require_mapping(evidence, "factor_scores", agent_type)
    factor_weights = _require_mapping(evidence, "factor_weights", agent_type)
    if set(factor_scores.keys()) != _FACTOR_SET:
        raise ExplainabilityDataError(
            f"candidate '{agent_type}' factor_scores keys {sorted(factor_scores.keys())} "
            f"do not match the expected factor set {sorted(_FACTOR_SET)}"
        )
    if set(factor_weights.keys()) != _FACTOR_SET:
        raise ExplainabilityDataError(
            f"candidate '{agent_type}' factor_weights keys {sorted(factor_weights.keys())} "
            f"do not match the expected factor set {sorted(_FACTOR_SET)}"
        )
    for factor in FACTOR_ORDER:
        _require_unit_interval(factor_scores, factor, agent_type, "factor_scores")
        _require_unit_interval(factor_weights, factor, agent_type, "factor_weights")


def _validate_exclusion_consistency(score: RoutingCandidateScore) -> None:
    code = score.evidence.get("exclusion_reason_code")
    if score.eligible:
        if code is not None:
            raise ExplainabilityDataError(
                f"candidate '{score.agent_type}' is eligible but "
                "evidence.exclusion_reason_code is set"
            )
    else:
        if not isinstance(code, str) or not code.strip():
            raise ExplainabilityDataError(
                f"candidate '{score.agent_type}' is excluded but "
                "evidence.exclusion_reason_code is missing"
            )


def validate_routing_decision(decision: RoutingDecision) -> None:
    """Reject a contradictory or malformed `RoutingDecision` snapshot outright.
    Never repairs the input — only confirms it is safe to explain, or raises
    `ExplainabilityDataError`."""
    for score in decision.candidates:
        _validate_evidence_shape(score)
        _validate_exclusion_consistency(score)

    if decision.manual_override:
        return

    # `selected_agent_type`/`selected_agent_types` cross-consistency (no
    # contradiction between the two, no duplicates) is already enforced by
    # `RoutingDecision`'s own model validators — nothing to repeat here.

    if decision.selected_agent_type is not None and decision.candidates:
        matches = [
            c for c in decision.candidates if c.agent_type == decision.selected_agent_type
        ]
        if not matches:
            raise ExplainabilityDataError(
                f"selected_agent_type '{decision.selected_agent_type}' is not among "
                "decision.candidates"
            )
        if not matches[0].eligible:
            raise ExplainabilityDataError(
                f"selected_agent_type '{decision.selected_agent_type}' is not eligible"
            )

    for agent_type in decision.selected_agent_types:
        matches = [c for c in decision.candidates if c.agent_type == agent_type]
        if not matches or not matches[0].eligible:
            raise ExplainabilityDataError(
                f"selected_agent_types entry '{agent_type}' is missing or ineligible "
                "among decision.candidates"
            )


def compute_decision_id(decision: RoutingDecision) -> str:
    """A deterministic, content-addressed decision identifier.

    `RoutingDecision` carries no `decision_id` field of its own (confirmed:
    `app.contracts.routing.RoutingDecision` has no identity field), so this
    derives one from the full decision snapshot rather than any
    runtime-generated value — no random UUID, no current timestamp. Formula:
    canonical JSON of `decision.model_dump(mode="json")` (recursively sorted
    keys, compact separators) -> UTF-8 bytes -> SHA-256 -> first 32 hex
    characters, prefixed `"routing-"`. Any two `RoutingDecision`s with
    identical field values (including `decided_at`, which is part of the
    decision itself, not "now") always produce the same id; any semantic
    difference between them always changes it.
    """
    payload = json.dumps(decision.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"routing-{digest[:32]}"


def compute_subject_id(decision: RoutingDecision) -> str:
    """The `DecisionTrace.subject_id`: the selected agent type when one was
    chosen, else the routed `task_type`. Derived purely from `decision` —
    Stage 4C has no access to an external workflow/step id at this layer."""
    return decision.selected_agent_type or decision.task_type


def _factor_sample_size(score: RoutingCandidateScore, factor: str) -> int:
    evidence = score.evidence
    if factor == "overall_reliability":
        return int(evidence["overall"]["execution_count"])
    if factor == "task_reliability":
        return int(evidence["task_specific"]["execution_count"])
    if factor == "repository_reliability":
        return int(evidence["repository_specific"]["execution_count"])
    return score.sample_size


def _score_contributions_for_candidate(score: RoutingCandidateScore) -> list[ScoreContribution]:
    factor_scores = score.evidence["factor_scores"]
    factor_weights = score.evidence["factor_weights"]
    contributions = []
    for factor in FACTOR_ORDER:
        raw = float(factor_scores[factor])
        weight = float(factor_weights[factor])
        contributions.append(
            safe_construct(
                ScoreContribution,
                factor_name=factor,
                raw_score=raw,
                weight=weight,
                weighted_contribution=round(raw * weight, 10),
                sample_size=_factor_sample_size(score, factor),
                low_sample_size=score.low_sample_size,
            )
        )
    return contributions


def build_score_contributions(decision: RoutingDecision) -> dict[str, list[ScoreContribution]]:
    """Full per-factor `ScoreContribution` breakdown for every candidate in
    `decision.candidates` — eligible or excluded alike, since
    `score_candidate` always computes the full breakdown regardless of
    eligibility. Answers both "why was X selected" and "why did Y rank
    lower"/"why was Z excluded" from the same data."""
    return {
        score.agent_type: _score_contributions_for_candidate(score) for score in decision.candidates
    }


def build_exclusions(decision: RoutingDecision) -> list[ExclusionReason]:
    """One `ExclusionReason` per ineligible candidate, in `decision.candidates`
    order."""
    exclusions = []
    for score in decision.candidates:
        if score.eligible:
            continue
        code = score.evidence.get("exclusion_reason_code")
        exclusions.append(
            safe_construct(
                ExclusionReason,
                candidate_id=score.agent_type,
                reason_code=str(code),
                reason_text=score.excluded_reason or "excluded",
            )
        )
    return exclusions


def _evidence_items_for_candidate(score: RoutingCandidateScore) -> list[EvidenceItem]:
    evidence = score.evidence
    return [
        safe_construct(
            EvidenceItem,
            kind="overall_reliability",
            description="Overall historical execution/success counts and smoothed reliability.",
            value=evidence["overall"],
            sample_size=evidence["overall"]["execution_count"],
        ),
        safe_construct(
            EvidenceItem,
            kind="task_specific_reliability",
            description=(
                "Task-type-specific historical execution/success counts and smoothed reliability."
            ),
            value=evidence["task_specific"],
            sample_size=evidence["task_specific"]["execution_count"],
        ),
        safe_construct(
            EvidenceItem,
            kind="repository_specific_reliability",
            description=(
                "Repository-specific historical execution/success counts and smoothed reliability."
            ),
            value=evidence["repository_specific"],
            sample_size=evidence["repository_specific"]["execution_count"],
        ),
        safe_construct(
            EvidenceItem,
            kind="latency",
            description="Raw measured median latency and its normalized routing score.",
            value=evidence["latency"],
        ),
        safe_construct(
            EvidenceItem,
            kind="cost",
            description="Raw measured cost estimate and its normalized routing score.",
            value=evidence["cost"],
        ),
        safe_construct(
            EvidenceItem,
            kind="availability",
            description="Live availability status and circuit breaker state at decision time.",
            value=evidence["availability"],
        ),
        safe_construct(
            EvidenceItem,
            kind="preference",
            description="Whether this candidate was among the caller's preferred agent types.",
            value=evidence["preference"],
        ),
        safe_construct(
            EvidenceItem,
            kind="capabilities",
            description="Required, declared, and missing capabilities considered for eligibility.",
            value=evidence["capabilities"],
        ),
        safe_construct(
            EvidenceItem,
            kind="constraints",
            description="Configured hard constraints evaluated for eligibility.",
            value=evidence["constraints"],
        ),
        safe_construct(
            EvidenceItem,
            kind="bootstrap_no_differentiating_evidence",
            description=(
                "Whether the composite score reflects no differentiating historical evidence "
                "at all."
            ),
            value=evidence["bootstrap_no_differentiating_evidence"],
        ),
    ]


def build_evidence_items(decision: RoutingDecision) -> list[EvidenceItem]:
    """The `DecisionTrace.evidence` for `decision`'s subject (the selected
    candidate, when one exists). A manual override has no per-candidate
    `evidence` dict at all (`Router._route_manual_override` always returns
    `candidates=[]`), so it gets one explicit, honest item saying so rather
    than fabricating factor evidence that was never computed. "No eligible
    candidate" decisions carry no subject to attach evidence to; the detail
    for that case lives entirely in `build_exclusions`."""
    if decision.manual_override:
        agent_type = decision.selected_agent_type or "unknown"
        return [
            safe_construct(
                EvidenceItem,
                kind="manual_override",
                description=(
                    "Agent type was selected directly by request; automatic scoring and "
                    "historical-evidence collection were bypassed for ranking (hard safety "
                    "checks still applied)."
                ),
                value=agent_type,
            )
        ]
    if decision.selected_agent_type is None:
        return []
    selected = next(
        (c for c in decision.candidates if c.agent_type == decision.selected_agent_type), None
    )
    if selected is None:
        return []
    return _evidence_items_for_candidate(selected)


__all__ = [
    "EXCLUSION_REASON_PHRASES",
    "FACTOR_ORDER",
    "ExplainabilityDataError",
    "build_evidence_items",
    "build_exclusions",
    "build_score_contributions",
    "compute_decision_id",
    "compute_subject_id",
    "safe_construct",
    "validate_routing_decision",
]
