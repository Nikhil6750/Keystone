"""Conservative `CounterfactualCondition` generation.

Two kinds of counterfactual are generated, both derived only from values
already present in the `RoutingDecision` snapshot — never a fabricated
number:

- **Exclusion counterfactuals**: for each ineligible candidate, one
  condition naming the configured constraint (or policy) it would need to
  satisfy, quoting the constraint's own configured value from
  `RoutingCandidateScore.evidence["constraints"]`/`["capabilities"]` (real
  values the request itself set, never invented thresholds).
- **Ranking counterfactuals**: for an eligible-but-not-selected candidate,
  one condition naming the selected candidate's own observed composite
  score as the bar it would need to clear. Skipped entirely for any
  candidate (or the selection itself) whose score reflects bootstrap
  ("no differentiating evidence") filler — an "exceeded X" claim about a
  neutral, evidence-free score would be misleading, not merely
  unederivable, so it is safer to omit it than to generate it.

`would_change_outcome_to` is set only for the single candidate that is both
eligible and immediately next in `decision.fallback_order` — the one case
where "if this candidate's score had been higher, it deterministically would
have been selected instead" is unambiguously true given the router's fixed
ranking rule. Every other counterfactual leaves it `None` rather than
guessing.
"""

from app.contracts.explainability import CounterfactualCondition
from app.contracts.routing import RoutingCandidateScore, RoutingDecision
from app.engine.explainability.routing import safe_construct
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


def _exclusion_counterfactual(score: RoutingCandidateScore) -> CounterfactualCondition | None:
    code = score.evidence.get("exclusion_reason_code")
    agent = score.agent_type
    constraints = score.evidence.get("constraints", {})
    capabilities = score.evidence.get("capabilities", {})

    if code == MISSING_CAPABILITY:
        missing = capabilities.get("missing") or []
        missing_text = ", ".join(missing) if missing else "the required capability"
        description = f"'{agent}' could become eligible if it declared {missing_text}."
    elif code in (RELIABILITY_BELOW_THRESHOLD, RELIABILITY_EVIDENCE_UNAVAILABLE):
        threshold = constraints.get("minimum_reliability")
        description = (
            f"'{agent}' could become eligible if its measured reliability satisfied "
            f"the configured minimum_reliability constraint ({threshold})."
        )
    elif code in (LATENCY_ABOVE_THRESHOLD, LATENCY_EVIDENCE_UNAVAILABLE, LATENCY_EVIDENCE_INVALID):
        threshold = constraints.get("max_latency_ms")
        description = (
            f"'{agent}' could become eligible if its measured latency fell within "
            f"the configured max_latency_ms constraint ({threshold})."
        )
    elif code in (COST_ABOVE_THRESHOLD, COST_EVIDENCE_UNAVAILABLE, COST_EVIDENCE_INVALID):
        threshold = constraints.get("max_cost_usd")
        description = (
            f"'{agent}' could become eligible if its measured cost satisfied "
            f"the configured max_cost_usd constraint ({threshold})."
        )
    elif code == CIRCUIT_OPEN:
        description = (
            f"'{agent}' could become eligible once its runtime health/circuit state "
            "permits use again."
        )
    elif code == RUNTIME_UNAVAILABLE:
        description = f"'{agent}' could become eligible once the runtime becomes available again."
    elif code == EXPLICITLY_EXCLUDED:
        description = (
            f"'{agent}' could become eligible if the explicit exclusion policy for it "
            "were removed."
        )
    else:
        return None

    return safe_construct(CounterfactualCondition, description=description)


def _is_bootstrap(score: RoutingCandidateScore) -> bool:
    return bool(score.evidence.get("bootstrap_no_differentiating_evidence"))


def _ranking_counterfactual(
    score: RoutingCandidateScore, selected: RoutingCandidateScore, would_change_outcome: bool
) -> CounterfactualCondition | None:
    if _is_bootstrap(score) or _is_bootstrap(selected):
        return None
    selected_composite = selected.composite_score
    if selected_composite is None:
        return None
    description = (
        f"'{score.agent_type}' could rank above the current selection if its measured "
        f"composite score exceeded {selected_composite:.3f} (the selected candidate's "
        "observed composite score)."
    )
    return safe_construct(
        CounterfactualCondition,
        description=description,
        would_change_outcome_to=score.agent_type if would_change_outcome else None,
    )


def generate_counterfactuals(decision: RoutingDecision) -> list[CounterfactualCondition]:
    """All conservatively derivable `CounterfactualCondition`s for `decision`.
    A manual override or a decision with no scored candidates has nothing
    safe to derive from and returns an empty list."""
    if decision.manual_override or not decision.candidates:
        return []

    conditions: list[CounterfactualCondition] = []
    for score in decision.candidates:
        if score.eligible:
            continue
        condition = _exclusion_counterfactual(score)
        if condition is not None:
            conditions.append(condition)

    selected_types = set(decision.selected_agent_types) or (
        {decision.selected_agent_type} if decision.selected_agent_type else set()
    )
    if not selected_types:
        return conditions

    primary = next(
        (c for c in decision.candidates if c.agent_type == decision.selected_agent_type), None
    )
    if primary is None:
        return conditions

    immediate_next = decision.fallback_order[0] if decision.fallback_order else None
    for score in decision.candidates:
        if not score.eligible or score.agent_type in selected_types:
            continue
        would_change = score.agent_type == immediate_next
        condition = _ranking_counterfactual(score, primary, would_change)
        if condition is not None:
            conditions.append(condition)

    return conditions


__all__ = ["generate_counterfactuals"]
