"""Tests for `app.engine.explainability.counterfactuals`: conservative
`CounterfactualCondition` generation from a `RoutingDecision` snapshot,
covering every documented exclusion-code family plus the single
ranking-loss case that safely implies "would change the outcome"."""

from typing import Any

from app.contracts.adapter import AgentDescriptor
from app.contracts.enums import AgentCapability, AgentStatus, RuntimeKind
from app.contracts.passports import AgentPassportMetricBucket
from app.contracts.routing import RoutingConstraints, RoutingRequest
from app.engine.explainability.counterfactuals import generate_counterfactuals
from app.engine.routing.availability import CandidateAgent
from app.engine.routing.router import Router
from app.resilience.circuit_breaker import CircuitState
from tests.support.routing_fakes import FakeEvidenceProvider


def _candidate(
    agent_type: str,
    *,
    status: AgentStatus = AgentStatus.AVAILABLE,
    circuit_state: CircuitState = CircuitState.CLOSED,
    capabilities: list[AgentCapability] | None = None,
) -> CandidateAgent:
    return CandidateAgent(
        descriptor=AgentDescriptor(
            agent_type=agent_type,
            display_name=agent_type,
            runtime_kind=RuntimeKind.AGENT_CLI,
            capabilities=capabilities or [AgentCapability.CODE_GENERATION],
        ),
        status=status,
        circuit_state=circuit_state,
    )


def _request(**overrides: Any) -> RoutingRequest:
    base: dict[str, Any] = {"task_type": "code_generation"}
    base.update(overrides)
    return RoutingRequest.model_validate(base)


def _descriptions(decision: Any) -> list[str]:
    return [c.description for c in generate_counterfactuals(decision)]


def test_counterfactual_for_missing_capability() -> None:
    router = Router()
    request = _request(required_capabilities=[AgentCapability.CODE_GENERATION])
    decision = router.route(
        request,
        [
            _candidate("claude_code"),
            _candidate("gemini", capabilities=[AgentCapability.CODE_REVIEW]),
        ],
    )
    descriptions = _descriptions(decision)
    assert any("gemini" in d and "declared" in d and "code_generation" in d for d in descriptions)


def test_counterfactual_for_reliability_threshold() -> None:
    evidence = FakeEvidenceProvider(
        overall={
            "claude_code": AgentPassportMetricBucket(execution_count=20, success_count=19),
            "codex": AgentPassportMetricBucket(execution_count=20, success_count=2),
        }
    )
    router = Router(evidence=evidence)
    request = _request(constraints=RoutingConstraints(minimum_reliability=0.5))
    decision = router.route(request, [_candidate("claude_code"), _candidate("codex")])
    descriptions = _descriptions(decision)
    assert any("codex" in d and "minimum_reliability" in d and "0.5" in d for d in descriptions)


def test_counterfactual_for_latency_threshold() -> None:
    evidence = FakeEvidenceProvider(
        overall={
            "codex": AgentPassportMetricBucket(
                execution_count=5, success_count=5, median_latency_ms=9000
            )
        }
    )
    router = Router(evidence=evidence)
    request = _request(constraints=RoutingConstraints(max_latency_ms=1000))
    decision = router.route(request, [_candidate("claude_code"), _candidate("codex")])
    descriptions = _descriptions(decision)
    assert any("codex" in d and "max_latency_ms" in d and "1000" in d for d in descriptions)


def test_counterfactual_for_cost_threshold() -> None:
    evidence = FakeEvidenceProvider(cost_usd={"codex": 5.0})
    router = Router(evidence=evidence)
    request = _request(constraints=RoutingConstraints(max_cost_usd=1.0))
    decision = router.route(request, [_candidate("claude_code"), _candidate("codex")])
    descriptions = _descriptions(decision)
    assert any("codex" in d and "max_cost_usd" in d and "1.0" in d for d in descriptions)


def test_counterfactual_for_circuit_open() -> None:
    router = Router()
    decision = router.route(
        _request(),
        [_candidate("claude_code"), _candidate("codex", circuit_state=CircuitState.OPEN)],
    )
    descriptions = _descriptions(decision)
    assert any("codex" in d and "circuit" in d for d in descriptions)


def test_counterfactual_for_explicit_exclusion() -> None:
    router = Router()
    request = _request(constraints=RoutingConstraints(excluded_agent_types=["codex"]))
    decision = router.route(request, [_candidate("claude_code"), _candidate("codex")])
    descriptions = _descriptions(decision)
    assert any("codex" in d and "exclusion policy" in d for d in descriptions)


def test_counterfactual_for_runtime_unavailable() -> None:
    router = Router()
    decision = router.route(
        _request(),
        [_candidate("claude_code"), _candidate("codex", status=AgentStatus.UNAVAILABLE)],
    )
    descriptions = _descriptions(decision)
    assert any("codex" in d and "available again" in d for d in descriptions)


def test_ranking_counterfactual_for_immediate_next_candidate_sets_would_change_outcome() -> None:
    evidence = FakeEvidenceProvider(
        overall={
            "claude_code": AgentPassportMetricBucket(execution_count=40, success_count=39),
            "codex": AgentPassportMetricBucket(execution_count=40, success_count=30),
        }
    )
    router = Router(evidence=evidence)
    decision = router.route(_request(), [_candidate("claude_code"), _candidate("codex")])
    assert decision.fallback_order == ["codex"]
    conditions = generate_counterfactuals(decision)
    codex_condition = next(
        c for c in conditions if "codex" in c.description and "rank above" in c.description
    )
    assert codex_condition.would_change_outcome_to == "codex"


def test_no_counterfactuals_for_manual_override() -> None:
    router = Router()
    decision = router.route(
        _request(manual_override_agent_type="claude_code"), [_candidate("claude_code")]
    )
    assert generate_counterfactuals(decision) == []


def test_no_counterfactuals_when_bootstrap_selected() -> None:
    router = Router()
    decision = router.route(_request(), [_candidate("claude_code"), _candidate("codex")])
    conditions = generate_counterfactuals(decision)
    # No exclusions exist (both eligible) and both candidates are bootstrap
    # (zero historical evidence) -- no ranking counterfactual should claim a
    # meaningful score threshold.
    assert not any("rank above" in c.description for c in conditions)
