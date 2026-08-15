"""Deterministic, transparent routing confidence.

**Not a probability of success.** `RoutingCandidateScore.composite_score` is
a ranking score built from normalized, weighted factors — it was never fit
against or validated against actual task outcomes, so treating it (or any
function of it) as "the probability this runtime will succeed" would be a
statistical claim this engine cannot back up. Every `Confidence.basis`
string produced here says so explicitly, and states instead what the value
*does* reflect: how much observable routing evidence supported the
selection, and how clearly separated the selected candidate was from the
next-best eligible alternative.

**Formula**, applied only to a genuine automatic-ranking selection (see the
special cases below):

    value = 0.5 * sample_component + 0.5 * separation_component

- `sample_component = min(1.0, selected.sample_size / 20)` — `20` is this
  module's documented reference point for "substantial" evidence (below it,
  scaled linearly toward `0.0` at zero executions).
- `separation_component = min(1.0, max(0.0, separation) / 0.15)`, where
  `separation = selected.composite_score - next_best.composite_score` and
  `next_best` is the highest-scoring other eligible candidate. `0.15` (15
  points of composite score) is this module's documented reference point for
  a "clear" separation.

Special cases, each documented on its own branch below and never averaged
into the generic formula: **bootstrap** (no differentiating evidence
existed at all — the composite score is meaningless neutral filler, so
confidence is pinned to `0.0` regardless of sample size or separation),
**single eligible candidate** (no `next_best` exists, so `value` is
`sample_component` alone — there is nothing to separate from), **exact
tie** (`separation == 0`, so `separation_component == 0.0` and the basis
says the deterministic tie-break decided the outcome, not evidence),
**manual override** (bypassed automatic ranking entirely — returns `None`
rather than inventing an automatic-routing confidence that was never
computed), and **no eligible candidate** (nothing was selected — returns
`None`).
"""

from app.contracts.explainability import Confidence
from app.contracts.routing import RoutingCandidateScore, RoutingDecision
from app.engine.explainability.routing import ExplainabilityDataError, safe_construct

_SUBSTANTIAL_SAMPLE_SIZE = 20
_CLEAR_SEPARATION_MARGIN = 0.15

_BASIS_SUFFIX = (
    " This reflects routing evidence support and composite-score separation "
    "between candidates, not a predicted probability of task success."
)


def _sample_component(sample_size: int) -> float:
    return max(0.0, min(1.0, sample_size / _SUBSTANTIAL_SAMPLE_SIZE))


def _find_candidate(decision: RoutingDecision, agent_type: str) -> RoutingCandidateScore:
    match = next((c for c in decision.candidates if c.agent_type == agent_type), None)
    if match is None:
        raise ExplainabilityDataError(
            f"selected_agent_type '{agent_type}' is not among decision.candidates"
        )
    return match


def compute_confidence(decision: RoutingDecision) -> Confidence | None:
    """The `DecisionTrace.confidence` for `decision`, or `None` when there is
    nothing to be confident about (manual override bypassed automatic
    ranking; no eligible candidate was found)."""
    if decision.manual_override:
        return None
    if decision.selected_agent_type is None:
        return None

    selected = _find_candidate(decision, decision.selected_agent_type)
    bootstrap = bool(selected.evidence.get("bootstrap_no_differentiating_evidence"))
    if bootstrap:
        return safe_construct(
            Confidence,
            value=0.0,
            basis=(
                "No historical evidence differentiated the eligible candidates; "
                "deterministic fallback ordering selected this candidate." + _BASIS_SUFFIX
            ),
            sample_size=selected.sample_size,
            low_sample_size=True,
        )

    eligible_others = [
        c for c in decision.candidates if c.eligible and c.agent_type != selected.agent_type
    ]
    sample_component = _sample_component(selected.sample_size)

    if not eligible_others:
        return safe_construct(
            Confidence,
            value=round(sample_component, 6),
            basis=(
                "Only one eligible candidate existed; confidence reflects its evidence "
                "sample size alone, with no competing candidate for score separation."
                + _BASIS_SUFFIX
            ),
            sample_size=selected.sample_size,
            low_sample_size=selected.low_sample_size,
        )

    next_best = max(
        eligible_others, key=lambda c: (c.composite_score or 0.0, c.sample_size, c.agent_type)
    )
    selected_score = selected.composite_score or 0.0
    next_score = next_best.composite_score or 0.0
    separation = max(0.0, selected_score - next_score)
    separation_component = max(0.0, min(1.0, separation / _CLEAR_SEPARATION_MARGIN))
    value = round(0.5 * sample_component + 0.5 * separation_component, 6)

    if separation <= 0.0:
        basis = (
            f"Tied with next-ranked eligible candidate '{next_best.agent_type}' on composite "
            "score; selection was decided by the deterministic tie-break (evidence sample "
            "size, then agent type), not by evidence of superiority." + _BASIS_SUFFIX
        )
    else:
        basis = (
            f"Based on {selected.sample_size} historical execution(s) and a composite-score "
            f"separation of {separation:.3f} from the next-ranked eligible candidate "
            f"'{next_best.agent_type}'." + _BASIS_SUFFIX
        )

    return safe_construct(
        Confidence,
        value=value,
        basis=basis,
        sample_size=selected.sample_size,
        low_sample_size=selected.low_sample_size,
    )


__all__ = ["compute_confidence"]
