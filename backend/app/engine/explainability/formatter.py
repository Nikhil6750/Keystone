"""Concise, deterministic, human-readable text for a routing decision.

`compose_explanation_text` builds the exact string later stored as
`DecisionTrace.summary`; `format_routing_explanation` is the public accessor
for callers who already have a built `RoutingExplanation` and just want its
text. No marketing language, no invented numbers — every value quoted here
comes from `decision`/`score_contributions`/`exclusions`/`confidence`,
already validated and built by `routing.py`/`confidence.py`.
"""

from app.contracts.explainability import (
    Confidence,
    ExclusionReason,
    RoutingExplanation,
    ScoreContribution,
)
from app.contracts.routing import RoutingDecision
from app.engine.explainability.routing import EXCLUSION_REASON_PHRASES

_TOP_FACTOR_COUNT = 2


def _humanize_factor(factor_name: str) -> str:
    return factor_name.replace("_", " ")


def _is_bootstrap_selection(decision: RoutingDecision) -> bool:
    selected = next(
        (c for c in decision.candidates if c.agent_type == decision.selected_agent_type), None
    )
    if selected is None:
        return False
    return bool(selected.evidence.get("bootstrap_no_differentiating_evidence"))


def _manual_override_text(decision: RoutingDecision) -> str:
    return (
        f"'{decision.selected_agent_type}' was selected by manual override after satisfying "
        "all configured hard constraints. Automatic ranking was not used."
    )


def _no_candidate_text(decision: RoutingDecision, exclusions: list[ExclusionReason]) -> str:
    if not exclusions:
        return (
            "No runtime satisfied all configured hard constraints for "
            f"task_type='{decision.task_type}'."
        )
    reasons = "; ".join(
        f"{exclusion.candidate_id} "
        f"{EXCLUSION_REASON_PHRASES.get(exclusion.reason_code, exclusion.reason_text)}"
        for exclusion in exclusions
    )
    return f"No runtime satisfied all configured hard constraints. {reasons}."


def _bootstrap_text(decision: RoutingDecision) -> str:
    selected = decision.selected_agent_type
    return (
        "No historical evidence differentiated the eligible runtimes. Keystone used "
        f"deterministic fallback ordering to select '{selected}'. This does not indicate "
        f"that '{selected}' is statistically superior."
    )


def _consensus_text(decision: RoutingDecision) -> str:
    members = ", ".join(f"'{agent_type}'" for agent_type in decision.selected_agent_types)
    return (
        f"'{decision.selected_agent_type}' was selected as the primary among "
        f"{len(decision.selected_agent_types)} consensus runtimes: {members}."
    )


def _normal_text(
    decision: RoutingDecision, score_contributions: dict[str, list[ScoreContribution]]
) -> str:
    selected = decision.selected_agent_type
    eligible_count = sum(1 for c in decision.candidates if c.eligible)
    contributions = score_contributions.get(selected, []) if selected else []
    top = sorted(contributions, key=lambda c: (-(c.weighted_contribution or 0.0), c.factor_name))[
        :_TOP_FACTOR_COUNT
    ]
    selected_score = next((c for c in decision.candidates if c.agent_type == selected), None)
    sample_size = selected_score.sample_size if selected_score is not None else 0
    second = decision.fallback_order[0] if decision.fallback_order else None

    parts = [f"'{selected}' was selected from {eligible_count} eligible runtime(s)."]
    if top:
        factor_text = " and ".join(_humanize_factor(c.factor_name) for c in top)
        parts.append(f"{factor_text.capitalize()} were its strongest measured signals.")
    parts.append(f"The decision used {sample_size} historical execution(s).")
    if second:
        parts.append(f"'{second}' ranked second.")
    return " ".join(parts)


def compose_explanation_text(
    decision: RoutingDecision,
    score_contributions: dict[str, list[ScoreContribution]],
    exclusions: list[ExclusionReason],
    confidence: Confidence | None,
) -> str:
    """Deterministic explanation text for `decision`, dispatched by decision
    shape. `confidence` is accepted for a stable signature (future wording
    may reference it) but every current template derives its wording
    entirely from `decision`/`score_contributions`/`exclusions`."""
    del confidence
    if decision.manual_override:
        return _manual_override_text(decision)
    if decision.selected_agent_type is None:
        return _no_candidate_text(decision, exclusions)
    if len(decision.selected_agent_types) > 1:
        return _consensus_text(decision)
    if _is_bootstrap_selection(decision):
        return _bootstrap_text(decision)
    return _normal_text(decision, score_contributions)


def format_routing_explanation(explanation: RoutingExplanation) -> str:
    """The stable, public accessor for a built `RoutingExplanation`'s
    human-readable text."""
    return explanation.trace.summary


__all__ = ["compose_explanation_text", "format_routing_explanation"]
