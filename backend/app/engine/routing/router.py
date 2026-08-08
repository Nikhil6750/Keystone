"""The router: ties availability, evidence, and scoring together into one
explainable `RoutingDecision`.

Manual override always wins immediately, bypassing scoring — but never
bypasses hard operational-safety checks (see `_route_manual_override`).
Otherwise every candidate is scored (`app.engine.routing.scorer`),
ineligible candidates are excluded with a stated reason, and the remaining
eligible candidates are ranked deterministically (`_ranking_key`):

1. higher composite score
2. higher evidence sample size (a tie between two candidates' scores is
   broken in favor of the one with more credible evidence behind it)
3. lexicographic `agent_type` (a final, fully input-order-independent
   tie-break, so declaration order never affects the result)

`RoutingConstraints.allow_parallel`/`consensus_size` select more than one
candidate (see `_route_parallel`) instead of a single primary; `Router`
never calls an external model and performs no I/O of its own — every input
(`candidates`, `evidence`) is supplied by the caller.
"""

from datetime import UTC, datetime

from app.contracts.routing import RoutingCandidateScore, RoutingDecision, RoutingRequest
from app.engine.routing.availability import CandidateAgent
from app.engine.routing.evidence import NullEvidenceProvider, RoutingEvidenceProvider
from app.engine.routing.explanation import (
    explain_manual_override,
    explain_no_candidates,
    explain_parallel_selection,
    explain_selection,
)
from app.engine.routing.scorer import (
    RoutingWeights,
    manual_override_safety_violation,
    score_candidate,
)


class RoutingError(ValueError):
    """Base class for typed, caller-input-shape routing errors raised by
    `Router.route` — never a bare/opaque exception, and never raised for a
    normal "no eligible candidate" *outcome* (that remains a valid,
    explainable `RoutingDecision`; see `Router.route`)."""


class UnknownManualOverrideAgentError(RoutingError):
    """Raised when `manual_override_agent_type` isn't among the provided candidates."""

    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type
        super().__init__(
            f"manual override agent type '{agent_type}' is not among the provided candidates"
        )


class UnsafeManualOverrideError(RoutingError):
    """Raised when a manual override target fails a hard operational-safety
    check (unavailable, circuit-open, or missing a required capability).
    Policy/soft constraints (excluded_agent_types, minimum_reliability,
    max_latency_ms, max_cost_usd, preferred_agent_types) are intentionally
    NOT checked here — a manual override is a privileged bypass of routing
    *policy*, never of operational safety. See `_route_manual_override`."""

    def __init__(self, agent_type: str, reason: str) -> None:
        self.agent_type = agent_type
        self.reason = reason
        super().__init__(
            f"manual override agent type '{agent_type}' failed a hard safety check: {reason}"
        )


class InsufficientConsensusCandidatesError(RoutingError):
    """Raised when `RoutingConstraints.consensus_size` requests more eligible
    candidates than are actually available. Carries every candidate's score
    (including exclusion reasons) so the caller can explain the shortfall
    without a second lookup."""

    def __init__(
        self, consensus_size: int, eligible_count: int, scores: list[RoutingCandidateScore]
    ) -> None:
        self.consensus_size = consensus_size
        self.eligible_count = eligible_count
        self.scores = scores
        super().__init__(
            f"consensus_size={consensus_size} requires {consensus_size} eligible candidates, "
            f"but only {eligible_count} were eligible"
        )


def _ranking_key(score: RoutingCandidateScore) -> tuple[float, int, str]:
    composite = score.composite_score if score.composite_score is not None else 0.0
    return (-composite, -score.sample_size, score.agent_type)


class Router:
    """Evaluates a `RoutingRequest` against a set of candidate agents."""

    def __init__(
        self,
        *,
        evidence: RoutingEvidenceProvider | None = None,
        weights: RoutingWeights | None = None,
    ) -> None:
        self._evidence = evidence or NullEvidenceProvider()
        self._weights = weights or RoutingWeights()

    def route(self, request: RoutingRequest, candidates: list[CandidateAgent]) -> RoutingDecision:
        now = datetime.now(UTC)

        if request.manual_override_agent_type is not None:
            return self._route_manual_override(request, candidates, now)

        pool = self._restrict_pool(request, candidates)
        scores = [
            score_candidate(candidate, request, self._evidence, self._weights)
            for candidate in pool
        ]
        eligible = [score for score in scores if score.eligible]

        if not eligible:
            return RoutingDecision(
                task_type=request.task_type,
                selected_agent_type=None,
                selected_agent_types=[],
                candidates=scores,
                fallback_order=[],
                manual_override=False,
                confidence=None,
                explanation=explain_no_candidates(scores, request),
                decided_at=now,
            )

        ranked = sorted(eligible, key=_ranking_key)

        if request.constraints.allow_parallel:
            return self._route_parallel(request, ranked, scores, now)

        selected = ranked[0]
        return RoutingDecision(
            task_type=request.task_type,
            selected_agent_type=selected.agent_type,
            selected_agent_types=[selected.agent_type],
            candidates=scores,
            fallback_order=[score.agent_type for score in ranked[1:]],
            manual_override=False,
            confidence=selected.composite_score,
            explanation=explain_selection(selected, scores),
            decided_at=now,
        )

    def _route_parallel(
        self,
        request: RoutingRequest,
        ranked: list[RoutingCandidateScore],
        scores: list[RoutingCandidateScore],
        now: datetime,
    ) -> RoutingDecision:
        consensus_size = request.constraints.consensus_size
        if consensus_size is not None:
            if len(ranked) < consensus_size:
                raise InsufficientConsensusCandidatesError(consensus_size, len(ranked), scores)
            chosen = ranked[:consensus_size]
        else:
            chosen = ranked

        remainder = ranked[len(chosen) :]
        primary = chosen[0]
        return RoutingDecision(
            task_type=request.task_type,
            selected_agent_type=primary.agent_type,
            selected_agent_types=[score.agent_type for score in chosen],
            candidates=scores,
            fallback_order=[score.agent_type for score in remainder],
            manual_override=False,
            confidence=primary.composite_score,
            explanation=explain_parallel_selection(chosen, scores),
            decided_at=now,
        )

    def _route_manual_override(
        self, request: RoutingRequest, candidates: list[CandidateAgent], now: datetime
    ) -> RoutingDecision:
        agent_type = request.manual_override_agent_type
        assert agent_type is not None  # narrowed by the caller before this is invoked
        match = next(
            (
                candidate
                for candidate in candidates
                if candidate.descriptor.agent_type == agent_type
            ),
            None,
        )
        if match is None:
            raise UnknownManualOverrideAgentError(agent_type)

        violation = manual_override_safety_violation(match, request)
        if violation is not None:
            raise UnsafeManualOverrideError(agent_type, violation)

        return RoutingDecision(
            task_type=request.task_type,
            selected_agent_type=agent_type,
            selected_agent_types=[agent_type],
            candidates=[],
            fallback_order=[],
            manual_override=True,
            confidence=None,
            explanation=explain_manual_override(agent_type),
            decided_at=now,
        )

    @staticmethod
    def _restrict_pool(
        request: RoutingRequest, candidates: list[CandidateAgent]
    ) -> list[CandidateAgent]:
        if request.candidate_agent_types is None:
            return candidates
        allowed = set(request.candidate_agent_types)
        return [candidate for candidate in candidates if candidate.descriptor.agent_type in allowed]


__all__ = [
    "InsufficientConsensusCandidatesError",
    "Router",
    "RoutingError",
    "UnknownManualOverrideAgentError",
    "UnsafeManualOverrideError",
]
