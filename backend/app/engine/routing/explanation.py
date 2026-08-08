"""Human-readable explanations for routing decisions.

Every `RoutingDecision.explanation` must be non-blank (enforced by the
contract itself, `app.contracts.routing.RoutingDecision`) — this module is
the one place that wording is composed, so it stays consistent regardless of
which path through the router produced the decision. This string stays
short and factual by design; the full per-factor breakdown each candidate's
score is built from lives in `RoutingCandidateScore.evidence["factor_scores"
/"factor_weights"]` (`app.engine.routing.scorer.score_candidate`) for
Stage 4C's Explainability Engine to format later.
"""

from app.contracts.routing import RoutingCandidateScore, RoutingRequest


def _excluded_text(all_scores: list[RoutingCandidateScore]) -> str:
    excluded = [score for score in all_scores if not score.eligible]
    if not excluded:
        return ""
    reasons = "; ".join(f"{score.agent_type} ({score.excluded_reason})" for score in excluded)
    return f" Excluded: {reasons}."


def explain_selection(
    selected: RoutingCandidateScore, all_scores: list[RoutingCandidateScore]
) -> str:
    score_text = f"composite score {selected.composite_score:.2f}"
    confidence_text = (
        "limited historical evidence" if selected.low_sample_size else "sufficient history"
    )
    return (
        f"Selected '{selected.agent_type}': {score_text}, {confidence_text}."
        f"{_excluded_text(all_scores)}"
    )


def explain_parallel_selection(
    chosen: list[RoutingCandidateScore], all_scores: list[RoutingCandidateScore]
) -> str:
    chosen_text = ", ".join(
        f"{score.agent_type} (score {score.composite_score:.2f})" for score in chosen
    )
    return (
        f"Selected {len(chosen)} candidate(s) for parallel execution: {chosen_text}."
        f"{_excluded_text(all_scores)}"
    )


def explain_no_candidates(
    all_scores: list[RoutingCandidateScore], request: RoutingRequest
) -> str:
    if not all_scores:
        return (
            "No candidate agents were provided to the router for "
            f"task_type='{request.task_type}'."
        )
    reasons = "; ".join(
        f"{score.agent_type} ({score.excluded_reason or 'not eligible'})" for score in all_scores
    )
    return f"No eligible candidate found for task_type='{request.task_type}'. {reasons}."


def explain_manual_override(agent_type: str) -> str:
    return (
        f"Manual override: '{agent_type}' selected directly by request, "
        "bypassing automatic scoring and soft/policy constraints (hard "
        "safety checks still apply)."
    )


__all__ = [
    "explain_manual_override",
    "explain_no_candidates",
    "explain_parallel_selection",
    "explain_selection",
]
