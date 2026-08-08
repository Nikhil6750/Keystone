"""The router: ties availability, evidence, and scoring together into one
explainable `RoutingDecision`.

The candidate pool must contain at most one `CandidateAgent` per
`agent_type` — a pool with a duplicate is ambiguous and rejected outright
(`DuplicateRoutingCandidateError`) rather than silently scoring the same
runtime twice or picking one arbitrarily.

Manual override selects a specific eligible candidate instead of letting
automatic ranking pick — it is a bypass of *ranking*, never of hard
safety/policy constraints. A manual override target must pass the exact
same `eligibility_violation` check as any other candidate (existence,
`excluded_agent_types`, effective required capabilities, availability,
circuit breaker, `minimum_reliability`, `max_latency_ms`, `max_cost_usd`);
only `preferred_agent_types` and the composite-score ranking itself are
bypassed, since those are the only two things that are genuinely about
*which eligible candidate to prefer*, not about whether a candidate is safe
or policy-compliant to use at all. See `_route_manual_override`.

Otherwise every candidate is scored (`app.engine.routing.scorer`),
ineligible candidates are excluded with a stated reason, and the remaining
eligible candidates are ranked deterministically (`_ranking_key`):

1. higher composite score
2. higher evidence sample size (a tie between two candidates' scores is
   broken in favor of the one with more credible evidence behind it)
3. lexicographic `agent_type` (a final, fully input-order-independent
   tie-break — this exists purely to make ties deterministic; it is never
   evidence of one candidate being genuinely better than another, and a
   `RoutingDecision`'s `evidence`/explanation says so explicitly whenever
   this tie-break is what actually decided the outcome — see
   `explanation.py`'s bootstrap-aware wording)

`RoutingConstraints.consensus_size` selects more than one candidate (see
`_route_consensus`) instead of a single primary; `allow_parallel=True` alone
(no `consensus_size`) means only that parallel execution is *permitted*, not
requested — it still resolves to ordinary single-candidate selection, since
nothing in the request actually asked for more than one runtime. `Router`
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
    eligibility_violation,
    score_candidate,
)


class RoutingError(ValueError):
    """Base class for typed, caller-input-shape routing errors raised by
    `Router.route` — never a bare/opaque exception, and never raised for a
    normal "no eligible candidate" *outcome* (that remains a valid,
    explainable `RoutingDecision`; see `Router.route`)."""


class DuplicateRoutingCandidateError(RoutingError):
    """Raised when the candidate pool contains more than one `CandidateAgent`
    for the same `agent_type` — an ambiguous input the router refuses to
    silently resolve by picking one arbitrarily or scoring the same runtime
    twice."""

    def __init__(self, duplicate_agent_types: list[str]) -> None:
        self.duplicate_agent_types = duplicate_agent_types
        super().__init__(
            "duplicate candidate agent_type(s) in routing pool: "
            + ", ".join(duplicate_agent_types)
        )


class UnknownManualOverrideAgentError(RoutingError):
    """Raised when `manual_override_agent_type` isn't among the provided candidates."""

    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type
        super().__init__(
            f"manual override agent type '{agent_type}' is not among the provided candidates"
        )


class UnsafeManualOverrideError(RoutingError):
    """Raised when a manual override target fails the same hard-eligibility
    check (`eligibility_violation`) every other candidate must pass:
    existence, `excluded_agent_types`, effective required capabilities,
    availability, circuit breaker, `minimum_reliability`, `max_latency_ms`,
    or `max_cost_usd`. A manual override bypasses automatic *ranking*
    (`preferred_agent_types` and the composite score) — never a hard
    safety or policy constraint. See `_route_manual_override`."""

    def __init__(self, agent_type: str, reason: str) -> None:
        self.agent_type = agent_type
        self.reason = reason
        super().__init__(
            f"manual override agent type '{agent_type}' failed a hard safety/policy "
            f"check: {reason}"
        )


class InsufficientConsensusCandidatesError(RoutingError):
    """Raised when `RoutingConstraints.consensus_size` requests more eligible
    candidates than are actually available.

    This intentionally differs from ordinary routing's "no eligible
    candidate" outcome, which returns a valid `RoutingDecision`
    (`selected_agent_type=None`) rather than raising: an open-ended
    single/multi-select request degrades gracefully to "no answer" because
    nothing specific was promised. `consensus_size=N` is a caller-declared,
    contract-validated cardinality requirement (`RoutingConstraints`
    requires `consensus_size >= 2` and `allow_parallel=True` to set it at
    all) — much closer in spirit to a manual override than to an
    open-ended search. Finding fewer than N eligible candidates means the
    specific thing the caller asked for cannot be fulfilled, not merely
    that ranking came up empty, so it is reported the same way an invalid
    manual override is: as a typed, caller-input-shape error, not a
    `RoutingDecision` outcome. Carries every candidate's score (including
    exclusion reasons) so the caller can explain the shortfall without a
    second lookup.
    """

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


def _find_duplicate_agent_types(candidates: list[CandidateAgent]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    already_reported: set[str] = set()
    for candidate in candidates:
        agent_type = candidate.descriptor.agent_type
        if agent_type in seen and agent_type not in already_reported:
            duplicates.append(agent_type)
            already_reported.add(agent_type)
        seen.add(agent_type)
    return duplicates


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
        duplicates = _find_duplicate_agent_types(candidates)
        if duplicates:
            raise DuplicateRoutingCandidateError(sorted(duplicates))

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

        consensus_size = request.constraints.consensus_size
        if consensus_size is not None:
            return self._route_consensus(request, ranked, scores, now, consensus_size)

        # `allow_parallel=True` alone (no `consensus_size`) only permits
        # parallel execution — it does not itself request more than one
        # runtime, so this resolves to ordinary single-candidate selection.
        # See the module docstring.
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

    def _route_consensus(
        self,
        request: RoutingRequest,
        ranked: list[RoutingCandidateScore],
        scores: list[RoutingCandidateScore],
        now: datetime,
        consensus_size: int,
    ) -> RoutingDecision:
        if len(ranked) < consensus_size:
            raise InsufficientConsensusCandidatesError(consensus_size, len(ranked), scores)
        chosen = ranked[:consensus_size]

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

        violation = eligibility_violation(match, request, self._evidence)
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
    "DuplicateRoutingCandidateError",
    "InsufficientConsensusCandidatesError",
    "Router",
    "RoutingError",
    "UnknownManualOverrideAgentError",
    "UnsafeManualOverrideError",
]
