"""End-to-end tests for `app.engine.explainability.explain_routing_decision`:
normal/bootstrap/manual-override/consensus/no-candidate decision shapes, the
human-readable formatter, safety (no hidden-reasoning leakage), and
determinism (repeated runs on the same `RoutingDecision` produce identical
output)."""

from typing import Any

import pytest

from app.contracts.adapter import AgentDescriptor
from app.contracts.enums import AgentCapability, AgentStatus, RuntimeKind
from app.contracts.explainability import DecisionType
from app.contracts.passports import AgentPassportMetricBucket
from app.contracts.routing import RoutingConstraints, RoutingRequest
from app.engine.explainability import (
    ExplainabilityDataError,
    explain_routing_decision,
    format_routing_explanation,
)
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


# --- NORMAL --------------------------------------------------------------------


def test_normal_selection_produces_a_complete_routing_explanation() -> None:
    evidence = FakeEvidenceProvider(
        overall={
            "claude_code": AgentPassportMetricBucket(execution_count=42, success_count=40),
            "codex": AgentPassportMetricBucket(execution_count=42, success_count=25),
        }
    )
    router = Router(evidence=evidence)
    decision = router.route(_request(), [_candidate("claude_code"), _candidate("codex")])
    explanation = explain_routing_decision(decision)

    assert explanation.trace.decision_type is DecisionType.ROUTING
    assert explanation.trace.subject_id == "claude_code"
    assert explanation.trace.confidence is not None
    assert "claude_code" in explanation.score_contributions
    assert "codex" in explanation.score_contributions
    assert explanation.exclusions == []
    text = format_routing_explanation(explanation)
    assert "claude_code" in text
    assert "2 eligible runtime" in text
    assert "codex" in text  # ranked second


# --- BOOTSTRAP -------------------------------------------------------------------


def test_bootstrap_selection_does_not_claim_statistical_superiority() -> None:
    router = Router()
    decision = router.route(_request(), [_candidate("claude_code"), _candidate("codex")])
    explanation = explain_routing_decision(decision)
    text = format_routing_explanation(explanation)
    assert "no historical evidence differentiated" in text.lower()
    assert "does not indicate" in text.lower()
    assert explanation.trace.confidence is not None
    assert explanation.trace.confidence.value == 0.0


# --- MANUAL OVERRIDE ---------------------------------------------------------------


def test_manual_override_bypasses_ranking_with_no_fabricated_confidence() -> None:
    router = Router()
    decision = router.route(
        _request(manual_override_agent_type="codex"),
        [_candidate("codex"), _candidate("claude_code")],
    )
    explanation = explain_routing_decision(decision)
    text = format_routing_explanation(explanation)
    assert "manual override" in text.lower()
    assert "automatic ranking was not used" in text.lower()
    assert explanation.trace.confidence is None
    assert explanation.score_contributions == {}
    assert explanation.exclusions == []


# --- CONSENSUS -----------------------------------------------------------------


def test_consensus_selection_represents_every_selected_runtime() -> None:
    evidence = FakeEvidenceProvider(
        overall={
            "a": AgentPassportMetricBucket(execution_count=10, success_count=9),
            "b": AgentPassportMetricBucket(execution_count=10, success_count=7),
            "c": AgentPassportMetricBucket(execution_count=10, success_count=2),
        }
    )
    router = Router(evidence=evidence)
    request = _request(constraints=RoutingConstraints(allow_parallel=True, consensus_size=2))
    decision = router.route(request, [_candidate("a"), _candidate("b"), _candidate("c")])
    assert decision.selected_agent_types == ["a", "b"]

    explanation = explain_routing_decision(decision)
    assert set(explanation.score_contributions.keys()) == {"a", "b", "c"}
    text = format_routing_explanation(explanation)
    assert "'a'" in text
    assert "primary" in text.lower()
    assert "'b'" in text  # every selected runtime represented in the text


# --- NO CANDIDATE ------------------------------------------------------------------


def test_no_eligible_candidate_explains_every_exclusion() -> None:
    router = Router()
    request = _request(required_capabilities=[AgentCapability.CODE_REVIEW])
    decision = router.route(
        request,
        [
            _candidate("claude_code"),  # missing required capability
            _candidate("codex", circuit_state=CircuitState.OPEN),  # missing required capability too
        ],
    )
    assert decision.selected_agent_type is None
    explanation = explain_routing_decision(decision)
    assert len(explanation.exclusions) == 2
    assert explanation.trace.confidence is None
    text = format_routing_explanation(explanation)
    assert "no runtime satisfied all configured hard constraints" in text.lower()
    assert "claude_code" in text
    assert "codex" in text


# --- MALFORMED --------------------------------------------------------------------


def test_explain_routing_decision_raises_typed_error_for_malformed_evidence() -> None:
    router = Router()
    decision = router.route(_request(), [_candidate("claude_code")])
    tampered = decision.candidates[0].model_copy(update={"evidence": {}})
    malformed_decision = decision.model_copy(update={"candidates": [tampered]})
    with pytest.raises(ExplainabilityDataError):
        explain_routing_decision(malformed_decision)


# --- SAFETY -------------------------------------------------------------------------


def test_forbidden_reasoning_shaped_evidence_is_blocked() -> None:
    router = Router()
    decision = router.route(_request(), [_candidate("claude_code")])
    score = decision.candidates[0]
    tampered_evidence = dict(score.evidence)
    tampered_evidence["overall"] = {**tampered_evidence["overall"], "chain_of_thought": "secret"}
    tampered_score = score.model_copy(update={"evidence": tampered_evidence})
    malformed_decision = decision.model_copy(update={"candidates": [tampered_score]})
    with pytest.raises(ExplainabilityDataError) as exc_info:
        explain_routing_decision(malformed_decision)
    assert "chain_of_thought" in str(exc_info.value) or "reasoning" in str(exc_info.value).lower()


def test_routing_explanation_never_carries_a_hidden_reasoning_field_name() -> None:
    router = Router()
    decision = router.route(_request(), [_candidate("claude_code"), _candidate("codex")])
    explanation = explain_routing_decision(decision)
    dumped = explanation.model_dump_json()
    for forbidden in ("chain_of_thought", "hidden_reasoning", "raw_prompt", "scratchpad"):
        assert forbidden not in dumped


# --- DETERMINISM ---------------------------------------------------------------------


def test_explain_routing_decision_is_deterministic_across_twenty_runs() -> None:
    evidence = FakeEvidenceProvider(
        overall={
            "claude_code": AgentPassportMetricBucket(execution_count=42, success_count=40),
            "codex": AgentPassportMetricBucket(execution_count=42, success_count=25),
        }
    )
    router = Router(evidence=evidence)
    decision = router.route(_request(), [_candidate("claude_code"), _candidate("codex")])

    results = [explain_routing_decision(decision) for _ in range(20)]
    first = results[0].model_dump_json()
    for result in results[1:]:
        assert result.model_dump_json() == first
