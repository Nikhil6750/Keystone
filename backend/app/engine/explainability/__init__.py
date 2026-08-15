"""Stage 4C: the Routing Explainability Engine.

Turns one already-produced `RoutingDecision` snapshot (`app.contracts.routing`)
into a structured `RoutingExplanation` (`app.contracts.explainability`) —
why a runtime was selected, why another ranked lower, why one was excluded,
what evidence and weights drove the score, how much historical evidence
existed, and what could conservatively have changed the outcome.

Read-only and backward-looking: this package never re-queries
`RoutingEvidenceProvider`, `AgentPassport`, availability services, or
`CircuitBreaker`; never calls an external model; never exposes hidden
chain-of-thought (`app.contracts.evidence_safety` blocks that at the
contract layer); and never mutates the `RoutingDecision` it explains. Same
input, same output, always — see each submodule's docstring for the exact
determinism guarantees (`routing.py`, `confidence.py`, `counterfactuals.py`,
`formatter.py`).

Does not implement the Planner/Orchestrator, the Verifier, or rerouting
execution, and does not change routing selection/scoring semantics — this
package only explains a decision `app.engine.routing.router.Router` already
made.
"""

from app.contracts.explainability import DecisionTrace, DecisionType, RoutingExplanation
from app.contracts.routing import RoutingDecision
from app.engine.explainability.confidence import compute_confidence
from app.engine.explainability.counterfactuals import generate_counterfactuals
from app.engine.explainability.formatter import compose_explanation_text, format_routing_explanation
from app.engine.explainability.routing import (
    ExplainabilityDataError,
    build_evidence_items,
    build_exclusions,
    build_score_contributions,
    compute_decision_id,
    compute_subject_id,
    validate_routing_decision,
)


def explain_routing_decision(decision: RoutingDecision) -> RoutingExplanation:
    """Build the full `RoutingExplanation` for `decision`.

    Raises `ExplainabilityDataError` if `decision` (or any candidate's
    `evidence` snapshot) is malformed or internally contradictory — never
    silently repairs it. `DecisionTrace.created_at` is `decision.decided_at`,
    not wall-clock time: the trace documents when the decision was made, and
    reusing that field (rather than calling `datetime.now()`) keeps this
    function's output identical across repeated calls on the same input.
    """
    validate_routing_decision(decision)

    score_contributions = build_score_contributions(decision)
    exclusions = build_exclusions(decision)
    evidence_items = build_evidence_items(decision)
    confidence = compute_confidence(decision)
    counterfactuals = generate_counterfactuals(decision)
    summary = compose_explanation_text(decision, score_contributions, exclusions, confidence)

    trace = DecisionTrace(
        decision_id=compute_decision_id(decision),
        decision_type=DecisionType.ROUTING,
        subject_id=compute_subject_id(decision),
        summary=summary,
        evidence=evidence_items,
        confidence=confidence,
        counterfactuals=counterfactuals,
        created_at=decision.decided_at,
    )
    return RoutingExplanation(
        decision=decision,
        trace=trace,
        score_contributions=score_contributions,
        exclusions=exclusions,
    )


__all__ = [
    "ExplainabilityDataError",
    "explain_routing_decision",
    "format_routing_explanation",
]
