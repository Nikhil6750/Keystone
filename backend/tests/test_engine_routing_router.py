"""Tests for `Router.route`: hard-constraint-aware selection, duplicate
-candidate rejection, manual override safety, parallel/consensus selection,
fallback ordering, and end-to-end determinism (including candidate-order
permutation invariance)."""

import itertools
from typing import Any

import pytest

from app.contracts.adapter import AgentDescriptor
from app.contracts.enums import AgentCapability, AgentStatus, RuntimeKind
from app.contracts.passports import AgentPassportMetricBucket
from app.contracts.routing import RoutingConstraints, RoutingRequest
from app.engine.routing.availability import CandidateAgent
from app.engine.routing.router import (
    DuplicateRoutingCandidateError,
    InsufficientConsensusCandidatesError,
    Router,
    UnknownManualOverrideAgentError,
    UnsafeManualOverrideError,
)
from app.resilience.circuit_breaker import CircuitState
from tests.support.routing_fakes import FakeEvidenceProvider


def _candidate(
    agent_type: str,
    *,
    status: AgentStatus = AgentStatus.AVAILABLE,
    circuit_state: CircuitState = CircuitState.CLOSED,
    runtime_kind: RuntimeKind = RuntimeKind.AGENT_CLI,
    capabilities: list[AgentCapability] | None = None,
) -> CandidateAgent:
    return CandidateAgent(
        descriptor=AgentDescriptor(
            agent_type=agent_type,
            display_name=agent_type,
            runtime_kind=runtime_kind,
            capabilities=capabilities or [AgentCapability.CODE_GENERATION],
        ),
        status=status,
        circuit_state=circuit_state,
    )


def _request(**overrides: Any) -> RoutingRequest:
    base: dict[str, Any] = {"task_type": "code_generation"}
    base.update(overrides)
    return RoutingRequest.model_validate(base)


# --- Duplicate candidate protection -------------------------------------------


def test_duplicate_agent_type_in_candidate_pool_is_rejected() -> None:
    router = Router()
    candidates = [_candidate("dup"), _candidate("dup"), _candidate("other")]
    with pytest.raises(DuplicateRoutingCandidateError) as exc_info:
        router.route(_request(), candidates)
    assert exc_info.value.duplicate_agent_types == ["dup"]


def test_duplicate_check_applies_even_under_manual_override() -> None:
    router = Router()
    candidates = [_candidate("dup"), _candidate("dup")]
    request = _request(manual_override_agent_type="dup")
    with pytest.raises(DuplicateRoutingCandidateError):
        router.route(request, candidates)


def test_duplicate_check_applies_even_with_no_eligible_candidates() -> None:
    router = Router()
    candidates = [
        _candidate("dup", status=AgentStatus.UNAVAILABLE),
        _candidate("dup", status=AgentStatus.UNAVAILABLE),
    ]
    with pytest.raises(DuplicateRoutingCandidateError):
        router.route(_request(), candidates)


def test_unique_candidate_pool_is_unaffected() -> None:
    router = Router()
    decision = router.route(_request(), [_candidate("a"), _candidate("b")])
    assert decision.selected_agent_type is not None


# --- Single-candidate selection ----------------------------------------------


def test_higher_composite_score_wins() -> None:
    evidence = FakeEvidenceProvider(
        overall={
            "claude_code": AgentPassportMetricBucket(execution_count=10, success_count=9),
            "codex": AgentPassportMetricBucket(execution_count=10, success_count=3),
        }
    )
    router = Router(evidence=evidence)
    candidates = [_candidate("claude_code"), _candidate("codex")]
    decision = router.route(_request(), candidates)
    assert decision.selected_agent_type == "claude_code"
    assert decision.selected_agent_types == ["claude_code"]
    assert decision.fallback_order == ["codex"]


def test_fallback_order_lists_remaining_eligible_candidates_by_rank() -> None:
    evidence = FakeEvidenceProvider(
        overall={
            "a": AgentPassportMetricBucket(execution_count=10, success_count=9),
            "b": AgentPassportMetricBucket(execution_count=10, success_count=6),
            "c": AgentPassportMetricBucket(execution_count=10, success_count=3),
        }
    )
    router = Router(evidence=evidence)
    candidates = [_candidate("c"), _candidate("a"), _candidate("b")]
    decision = router.route(_request(), candidates)
    assert decision.selected_agent_type == "a"
    assert decision.fallback_order == ["b", "c"]


def test_tie_breaks_deterministically_by_agent_type() -> None:
    router = Router()  # no evidence at all -> every candidate ties at 0.625
    candidates = [_candidate("zeta"), _candidate("alpha"), _candidate("mid")]
    decision = router.route(_request(), candidates)
    assert decision.selected_agent_type == "alpha"
    assert decision.fallback_order == ["mid", "zeta"]


def test_tie_break_prefers_larger_sample_size_before_lexicographic_order() -> None:
    """Two candidates tied on composite score are broken by whichever has
    more credible evidence behind it, before falling back to agent_type."""
    evidence = FakeEvidenceProvider(
        overall={
            # Both smooth to the same reliability (0.75), but "large" has
            # far more evidence backing that number.
            "large": AgentPassportMetricBucket(execution_count=298, success_count=224),
            "small": AgentPassportMetricBucket(execution_count=2, success_count=2),
        }
    )
    router = Router(evidence=evidence)
    candidates = [_candidate("small"), _candidate("large")]
    scores = {
        score.agent_type: score.reliability_score
        for score in router.route(_request(), candidates).candidates
    }
    assert scores["large"] == pytest.approx(scores["small"], abs=1e-9)
    decision = router.route(_request(), candidates)
    assert decision.selected_agent_type == "large"


def test_routing_decision_is_deterministic_for_identical_inputs() -> None:
    evidence = FakeEvidenceProvider(
        overall={"claude_code": AgentPassportMetricBucket(execution_count=10, success_count=7)}
    )
    router = Router(evidence=evidence)
    candidates = [_candidate("claude_code"), _candidate("codex")]
    request = _request()
    first = router.route(request, candidates)
    second = router.route(request, candidates)
    assert first.selected_agent_type == second.selected_agent_type
    assert first.fallback_order == second.fallback_order
    assert first.confidence == second.confidence


def test_candidate_agent_types_restricts_the_pool() -> None:
    router = Router()
    candidates = [_candidate("claude_code"), _candidate("codex"), _candidate("demo")]
    request = _request(candidate_agent_types=["demo"])
    decision = router.route(request, candidates)
    assert decision.selected_agent_type == "demo"
    assert {score.agent_type for score in decision.candidates} == {"demo"}


def test_bootstrap_candidate_with_no_evidence_can_still_be_selected() -> None:
    router = Router()
    decision = router.route(_request(), [_candidate("brand_new_agent")])
    assert decision.selected_agent_type == "brand_new_agent"
    assert decision.confidence == pytest.approx(0.625)


def test_bootstrap_explanation_does_not_claim_statistical_superiority() -> None:
    router = Router()
    decision = router.route(_request(), [_candidate("claude_code"), _candidate("codex")])
    assert "No historical evidence differentiated" in decision.explanation
    assert "claude_code" in decision.explanation
    assert "composite score" not in decision.explanation


def test_non_bootstrap_explanation_mentions_composite_score() -> None:
    evidence = FakeEvidenceProvider(
        overall={"claude_code": AgentPassportMetricBucket(execution_count=10, success_count=8)}
    )
    router = Router(evidence=evidence)
    decision = router.route(_request(), [_candidate("claude_code")])
    assert "composite score" in decision.explanation


def test_every_decision_has_a_non_blank_explanation() -> None:
    router = Router()
    scenarios = [
        router.route(_request(), []),
        router.route(_request(), [_candidate("a")]),
        router.route(_request(manual_override_agent_type="a"), [_candidate("a")]),
    ]
    for decision in scenarios:
        assert decision.explanation.strip() != ""


def test_preference_does_not_override_a_hard_exclusion() -> None:
    """A preferred candidate that fails a hard constraint stays excluded —
    preference is soft ranking only, never a safety/eligibility override."""
    router = Router()
    request = _request(constraints=RoutingConstraints(preferred_agent_types=["broken"]))
    candidates = [_candidate("broken", status=AgentStatus.UNAVAILABLE), _candidate("healthy")]
    decision = router.route(request, candidates)
    assert decision.selected_agent_type == "healthy"


# --- No eligible candidates ---------------------------------------------------


def test_no_eligible_candidates_returns_an_explained_none_selection() -> None:
    router = Router()
    candidates = [_candidate("claude_code", status=AgentStatus.UNAVAILABLE)]
    decision = router.route(_request(), candidates)
    assert decision.selected_agent_type is None
    assert decision.selected_agent_types == []
    assert "claude_code" in decision.explanation
    assert decision.candidates[0].excluded_reason == "agent unavailable"


def test_empty_candidate_list_returns_an_explained_none_selection() -> None:
    router = Router()
    decision = router.route(_request(), [])
    assert decision.selected_agent_type is None
    assert decision.explanation


# --- Cost constraint without a cost evidence provider (Fix 13) --------------


def test_max_cost_usd_without_any_cost_evidence_source_excludes_everyone() -> None:
    """Documented product behavior: no `RoutingEvidenceProvider`
    implementation reports real cost data yet, so a caller-configured
    `max_cost_usd` cannot currently be satisfied by any candidate — this is
    the safe, intentional consequence of "missing evidence never proves
    compliance," not a bug to work around."""
    router = Router()  # NullEvidenceProvider: cost_usd_estimate always None
    request = _request(constraints=RoutingConstraints(max_cost_usd=5.0))
    decision = router.route(request, [_candidate("a"), _candidate("b")])
    assert decision.selected_agent_type is None
    for score in decision.candidates:
        assert score.excluded_reason == "no cost evidence available to satisfy max_cost_usd"


# --- Manual override ------------------------------------------------------------


def test_manual_override_selects_the_requested_agent_directly() -> None:
    router = Router()
    candidates = [_candidate("claude_code"), _candidate("codex")]
    request = _request(manual_override_agent_type="codex")
    decision = router.route(request, candidates)
    assert decision.selected_agent_type == "codex"
    assert decision.selected_agent_types == ["codex"]
    assert decision.manual_override is True
    assert "Manual override" in decision.explanation


def test_manual_override_bypasses_preferred_agent_types() -> None:
    router = Router()
    candidates = [_candidate("codex"), _candidate("claude_code")]
    request = _request(
        manual_override_agent_type="codex",
        constraints=RoutingConstraints(preferred_agent_types=["claude_code"]),
    )
    decision = router.route(request, candidates)
    assert decision.selected_agent_type == "codex"


def test_manual_override_for_unknown_agent_type_raises() -> None:
    router = Router()
    candidates = [_candidate("claude_code")]
    request = _request(manual_override_agent_type="nonexistent")
    with pytest.raises(UnknownManualOverrideAgentError):
        router.route(request, candidates)


@pytest.mark.parametrize(
    ("build_candidates", "build_constraints", "expected_match", "required_capabilities"),
    [
        (
            lambda: [_candidate("codex", status=AgentStatus.UNAVAILABLE)],
            lambda: RoutingConstraints(),
            "unavailable",
            None,
        ),
        (
            lambda: [_candidate("codex", status=AgentStatus.UNKNOWN)],
            lambda: RoutingConstraints(),
            "unavailable",
            None,
        ),
        (
            lambda: [_candidate("codex", circuit_state=CircuitState.OPEN)],
            lambda: RoutingConstraints(),
            "circuit breaker open",
            None,
        ),
        (
            lambda: [_candidate("codex", capabilities=[AgentCapability.DOCUMENTATION])],
            lambda: RoutingConstraints(),
            "missing required capabilities",
            [AgentCapability.CODE_GENERATION],
        ),
        (
            lambda: [_candidate("codex")],
            lambda: RoutingConstraints(excluded_agent_types=["codex"]),
            "excluded by routing constraints",
            None,
        ),
        (
            lambda: [_candidate("codex")],
            lambda: RoutingConstraints(minimum_reliability=0.5),
            "no reliability evidence available",
            None,
        ),
        (
            lambda: [_candidate("codex")],
            lambda: RoutingConstraints(max_latency_ms=1000.0),
            "no latency evidence available",
            None,
        ),
        (
            lambda: [_candidate("codex")],
            lambda: RoutingConstraints(max_cost_usd=1.0),
            "no cost evidence available",
            None,
        ),
    ],
    ids=[
        "unavailable",
        "unknown_status",
        "circuit_open",
        "missing_capability",
        "excluded_agent_types",
        "minimum_reliability",
        "max_latency_ms",
        "max_cost_usd",
    ],
)
def test_manual_override_is_blocked_by_every_hard_constraint(
    build_candidates: Any,
    build_constraints: Any,
    expected_match: str,
    required_capabilities: list[AgentCapability] | None,
) -> None:
    """Manual override selects an *eligible* runtime instead of letting
    automatic ranking pick — it must satisfy the exact same hard-constraint
    set as ordinary routing. Only `preferred_agent_types` and composite
    ranking are bypassed (see `test_manual_override_bypasses_preferred_agent_types`)."""
    router = Router()
    candidates = build_candidates()
    kwargs: dict[str, Any] = {
        "manual_override_agent_type": "codex",
        "constraints": build_constraints(),
    }
    if required_capabilities is not None:
        kwargs["required_capabilities"] = required_capabilities
    request = _request(**kwargs)
    with pytest.raises(UnsafeManualOverrideError, match=expected_match):
        router.route(request, candidates)


def test_manual_override_for_agent_satisfying_every_hard_constraint_succeeds() -> None:
    evidence = FakeEvidenceProvider(
        overall={
            "codex": AgentPassportMetricBucket(
                execution_count=10, success_count=9, median_latency_ms=500.0
            )
        },
        cost_usd={"codex": 0.5},
    )
    router = Router(evidence=evidence)
    request = _request(
        manual_override_agent_type="codex",
        constraints=RoutingConstraints(
            minimum_reliability=0.5, max_latency_ms=1000.0, max_cost_usd=1.0
        ),
    )
    decision = router.route(request, [_candidate("codex")])
    assert decision.selected_agent_type == "codex"
    assert decision.manual_override is True


# --- Parallel / consensus selection (Fix 6/7) --------------------------------


def test_allow_parallel_alone_selects_a_single_primary_not_every_eligible_candidate() -> None:
    """`allow_parallel=True` alone only *permits* parallel execution — it
    does not request it. Only an explicit `consensus_size` triggers actual
    multi-selection (see `router.py`'s module docstring)."""
    router = Router()
    request = _request(constraints=RoutingConstraints(allow_parallel=True))
    candidates = [_candidate("a"), _candidate("b"), _candidate("c")]
    decision = router.route(request, candidates)
    assert len(decision.selected_agent_types) == 1
    assert decision.selected_agent_type in {"a", "b", "c"}


def test_allow_parallel_alone_with_thirty_candidates_does_not_fan_out() -> None:
    router = Router()
    request = _request(constraints=RoutingConstraints(allow_parallel=True))
    candidates = [_candidate(f"runtime_{i:02d}") for i in range(30)]
    decision = router.route(request, candidates)
    assert len(decision.selected_agent_types) == 1
    assert len(decision.fallback_order) == 29


def test_consensus_size_selects_exactly_n_top_ranked_candidates() -> None:
    evidence = FakeEvidenceProvider(
        overall={
            "a": AgentPassportMetricBucket(execution_count=10, success_count=9),
            "b": AgentPassportMetricBucket(execution_count=10, success_count=7),
            "c": AgentPassportMetricBucket(execution_count=10, success_count=2),
        }
    )
    router = Router(evidence=evidence)
    request = _request(constraints=RoutingConstraints(allow_parallel=True, consensus_size=2))
    candidates = [_candidate("a"), _candidate("b"), _candidate("c")]
    decision = router.route(request, candidates)
    assert decision.selected_agent_types == ["a", "b"]
    assert decision.selected_agent_type == "a"
    assert decision.fallback_order == ["c"]


def test_consensus_size_with_thirty_eligible_candidates_selects_exactly_n() -> None:
    router = Router()
    request = _request(constraints=RoutingConstraints(allow_parallel=True, consensus_size=5))
    candidates = [_candidate(f"runtime_{i:02d}") for i in range(30)]
    decision = router.route(request, candidates)
    assert len(decision.selected_agent_types) == 5
    assert len(decision.fallback_order) == 25


def test_insufficient_eligible_candidates_for_consensus_raises_typed_error() -> None:
    router = Router()
    request = _request(constraints=RoutingConstraints(allow_parallel=True, consensus_size=3))
    candidates = [_candidate("a"), _candidate("b", status=AgentStatus.UNAVAILABLE)]
    with pytest.raises(InsufficientConsensusCandidatesError) as exc_info:
        router.route(request, candidates)
    assert exc_info.value.consensus_size == 3
    assert exc_info.value.eligible_count == 1
    assert len(exc_info.value.scores) == 2


def test_selected_agent_type_is_the_first_entry_of_selected_agent_types_in_consensus_mode() -> None:
    evidence = FakeEvidenceProvider(
        overall={
            "a": AgentPassportMetricBucket(execution_count=10, success_count=9),
            "b": AgentPassportMetricBucket(execution_count=10, success_count=5),
        }
    )
    router = Router(evidence=evidence)
    request = _request(constraints=RoutingConstraints(allow_parallel=True, consensus_size=2))
    decision = router.route(request, [_candidate("a"), _candidate("b")])
    assert decision.selected_agent_type == decision.selected_agent_types[0]


def test_selected_agent_types_never_contains_duplicates_in_consensus_mode() -> None:
    router = Router()
    request = _request(constraints=RoutingConstraints(allow_parallel=True, consensus_size=3))
    candidates = [_candidate("a"), _candidate("b"), _candidate("c")]
    decision = router.route(request, candidates)
    assert len(decision.selected_agent_types) == len(set(decision.selected_agent_types))


def test_consensus_bootstrap_explanation_does_not_claim_statistical_superiority() -> None:
    router = Router()
    request = _request(constraints=RoutingConstraints(allow_parallel=True, consensus_size=2))
    decision = router.route(request, [_candidate("a"), _candidate("b"), _candidate("c")])
    assert "No historical evidence differentiated" in decision.explanation


# --- Circuit breaker: HALF_OPEN (Fix 12) -------------------------------------


def test_half_open_circuit_candidate_remains_selectable_at_the_router_level() -> None:
    router = Router()
    candidates = [_candidate("half_open_agent", circuit_state=CircuitState.HALF_OPEN)]
    decision = router.route(_request(), candidates)
    assert decision.selected_agent_type == "half_open_agent"


def test_half_open_beats_nothing_but_open_still_excludes() -> None:
    router = Router()
    candidates = [
        _candidate("half_open_agent", circuit_state=CircuitState.HALF_OPEN),
        _candidate("open_agent", circuit_state=CircuitState.OPEN),
    ]
    decision = router.route(_request(), candidates)
    assert decision.selected_agent_type == "half_open_agent"
    excluded = {score.agent_type: score.excluded_reason for score in decision.candidates}
    assert excluded["open_agent"] == "circuit breaker open"


# --- Universal runtime handling -------------------------------------------------


def test_one_candidate_pool_spanning_every_runtime_kind_routes_uniformly() -> None:
    """A single pool mixing every `RuntimeKind` must travel through the same
    `Router` code path with no provider- or runtime-kind-specific branching —
    selection is driven entirely by capability match and evidence."""
    candidates = [
        _candidate("agent_cli_runtime", runtime_kind=RuntimeKind.AGENT_CLI),
        _candidate("model_api_runtime", runtime_kind=RuntimeKind.MODEL_API),
        _candidate("local_model_runtime", runtime_kind=RuntimeKind.LOCAL_MODEL),
        _candidate("hybrid_runtime", runtime_kind=RuntimeKind.HYBRID),
    ]
    evidence = FakeEvidenceProvider(
        overall={
            "model_api_runtime": AgentPassportMetricBucket(execution_count=20, success_count=19)
        }
    )
    router = Router(evidence=evidence)
    decision = router.route(_request(), candidates)
    assert decision.selected_agent_type == "model_api_runtime"
    assert set(decision.fallback_order) == {
        "agent_cli_runtime",
        "local_model_runtime",
        "hybrid_runtime",
    }


# --- Determinism: candidate-order permutation invariance --------------------


def test_selection_is_invariant_to_candidate_order_including_exact_ties() -> None:
    evidence = FakeEvidenceProvider(
        overall={
            "a": AgentPassportMetricBucket(execution_count=10, success_count=9),
            "b": AgentPassportMetricBucket(execution_count=10, success_count=9),  # exact tie
            "c": AgentPassportMetricBucket(execution_count=10, success_count=3),
        }
    )
    router = Router(evidence=evidence)
    request = _request()
    results = set()
    for permutation in itertools.permutations(
        [_candidate("a"), _candidate("b"), _candidate("c")]
    ):
        decision = router.route(request, list(permutation))
        results.add(
            (decision.selected_agent_type, tuple(decision.fallback_order), decision.confidence)
        )
    assert len(results) == 1


def test_parallel_selection_is_invariant_to_candidate_order() -> None:
    evidence = FakeEvidenceProvider(
        overall={
            "a": AgentPassportMetricBucket(execution_count=10, success_count=9),
            "b": AgentPassportMetricBucket(execution_count=10, success_count=5),
            "c": AgentPassportMetricBucket(execution_count=10, success_count=1),
        }
    )
    router = Router(evidence=evidence)
    request = _request(constraints=RoutingConstraints(allow_parallel=True, consensus_size=2))
    results = set()
    for permutation in itertools.permutations(
        [_candidate("a"), _candidate("b"), _candidate("c")]
    ):
        decision = router.route(request, list(permutation))
        results.add((tuple(decision.selected_agent_types), tuple(decision.fallback_order)))
    assert len(results) == 1


def test_bootstrap_tie_selection_is_invariant_to_candidate_order() -> None:
    """No evidence at all -> every candidate ties at 0.625; the final
    lexicographic tie-break must still be independent of input order."""
    router = Router()
    request = _request()
    results = set()
    for permutation in itertools.permutations(
        [_candidate("zeta"), _candidate("alpha"), _candidate("mid")]
    ):
        decision = router.route(request, list(permutation))
        results.add((decision.selected_agent_type, tuple(decision.fallback_order)))
    assert len(results) == 1
