"""Tests for `Router.route`: hard-constraint-aware selection, manual
override safety, parallel/consensus selection, fallback ordering, and
end-to-end determinism."""

from typing import Any

import pytest

from app.contracts.adapter import AgentDescriptor
from app.contracts.enums import AgentCapability, AgentStatus, RuntimeKind
from app.contracts.passports import AgentPassportMetricBucket
from app.contracts.routing import RoutingConstraints, RoutingRequest
from app.engine.routing.availability import CandidateAgent
from app.engine.routing.router import (
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
    # Sanity: the two really do tie on the smoothed reliability score.
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
    request = _request(
        constraints=RoutingConstraints(preferred_agent_types=["broken"])
    )
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


# --- Manual override -----------------------------------------------------------


def test_manual_override_selects_the_requested_agent_directly() -> None:
    router = Router()
    candidates = [_candidate("claude_code"), _candidate("codex")]
    request = _request(manual_override_agent_type="codex")
    decision = router.route(request, candidates)
    assert decision.selected_agent_type == "codex"
    assert decision.selected_agent_types == ["codex"]
    assert decision.manual_override is True
    assert "Manual override" in decision.explanation


def test_manual_override_bypasses_soft_policy_constraints() -> None:
    router = Router()
    candidates = [_candidate("codex")]
    request = _request(
        manual_override_agent_type="codex",
        constraints=RoutingConstraints(excluded_agent_types=["codex"], minimum_reliability=0.99),
    )
    decision = router.route(request, candidates)
    assert decision.selected_agent_type == "codex"


def test_manual_override_for_unknown_agent_type_raises() -> None:
    router = Router()
    candidates = [_candidate("claude_code")]
    request = _request(manual_override_agent_type="nonexistent")
    with pytest.raises(UnknownManualOverrideAgentError):
        router.route(request, candidates)


def test_manual_override_for_unavailable_agent_raises_unsafe_error() -> None:
    router = Router()
    candidates = [_candidate("codex", status=AgentStatus.UNAVAILABLE)]
    request = _request(manual_override_agent_type="codex")
    with pytest.raises(UnsafeManualOverrideError, match="unavailable"):
        router.route(request, candidates)


def test_manual_override_for_open_circuit_agent_raises_unsafe_error() -> None:
    router = Router()
    candidates = [_candidate("codex", circuit_state=CircuitState.OPEN)]
    request = _request(manual_override_agent_type="codex")
    with pytest.raises(UnsafeManualOverrideError, match="circuit breaker open"):
        router.route(request, candidates)


def test_manual_override_for_agent_missing_a_required_capability_raises_unsafe_error() -> None:
    router = Router()
    candidates = [_candidate("codex", capabilities=[AgentCapability.DOCUMENTATION])]
    request = _request(
        manual_override_agent_type="codex",
        required_capabilities=[AgentCapability.CODE_GENERATION],
    )
    with pytest.raises(UnsafeManualOverrideError, match="missing required capabilities"):
        router.route(request, candidates)


# --- Parallel / consensus selection --------------------------------------------


def test_allow_parallel_false_selects_a_single_primary() -> None:
    router = Router()
    candidates = [_candidate("a"), _candidate("b")]
    decision = router.route(_request(), candidates)
    assert len(decision.selected_agent_types) == 1


def test_allow_parallel_true_without_consensus_size_selects_all_eligible() -> None:
    router = Router()
    request = _request(constraints=RoutingConstraints(allow_parallel=True))
    candidates = [_candidate("a"), _candidate("b"), _candidate("c")]
    decision = router.route(request, candidates)
    assert set(decision.selected_agent_types) == {"a", "b", "c"}
    assert decision.fallback_order == []


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


def test_insufficient_eligible_candidates_for_consensus_raises_typed_error() -> None:
    router = Router()
    request = _request(constraints=RoutingConstraints(allow_parallel=True, consensus_size=3))
    candidates = [_candidate("a"), _candidate("b", status=AgentStatus.UNAVAILABLE)]
    with pytest.raises(InsufficientConsensusCandidatesError) as exc_info:
        router.route(request, candidates)
    assert exc_info.value.consensus_size == 3
    assert exc_info.value.eligible_count == 1
    assert len(exc_info.value.scores) == 2


def test_selected_agent_type_is_the_first_entry_of_selected_agent_types_in_parallel_mode() -> None:
    evidence = FakeEvidenceProvider(
        overall={
            "a": AgentPassportMetricBucket(execution_count=10, success_count=9),
            "b": AgentPassportMetricBucket(execution_count=10, success_count=5),
        }
    )
    router = Router(evidence=evidence)
    request = _request(constraints=RoutingConstraints(allow_parallel=True))
    decision = router.route(request, [_candidate("a"), _candidate("b")])
    assert decision.selected_agent_type == decision.selected_agent_types[0]


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
