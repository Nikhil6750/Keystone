"""Tests for `app.engine.explainability.confidence`: deterministic,
non-probabilistic routing confidence across bootstrap, low/high sample,
exact-tie, single-candidate, manual-override, and no-candidate cases."""

from typing import Any

from app.contracts.adapter import AgentDescriptor
from app.contracts.enums import AgentCapability, AgentStatus, RuntimeKind
from app.contracts.passports import AgentPassportMetricBucket
from app.contracts.routing import RoutingRequest
from app.engine.explainability.confidence import compute_confidence
from app.engine.routing.availability import CandidateAgent
from app.engine.routing.router import Router
from app.resilience.circuit_breaker import CircuitState
from tests.support.routing_fakes import FakeEvidenceProvider


def _candidate(agent_type: str) -> CandidateAgent:
    return CandidateAgent(
        descriptor=AgentDescriptor(
            agent_type=agent_type,
            display_name=agent_type,
            runtime_kind=RuntimeKind.AGENT_CLI,
            capabilities=[AgentCapability.CODE_GENERATION],
        ),
        status=AgentStatus.AVAILABLE,
        circuit_state=CircuitState.CLOSED,
    )


def _request(**overrides: Any) -> RoutingRequest:
    base: dict[str, Any] = {"task_type": "code_generation"}
    base.update(overrides)
    return RoutingRequest.model_validate(base)


def test_confidence_is_zero_and_flags_bootstrap_when_no_evidence_exists() -> None:
    router = Router()
    decision = router.route(_request(), [_candidate("claude_code")])
    confidence = compute_confidence(decision)
    assert confidence is not None
    assert confidence.value == 0.0
    assert confidence.low_sample_size is True
    assert "no historical evidence" in confidence.basis.lower()
    assert "not a predicted probability" in confidence.basis.lower()


def test_confidence_reflects_low_sample_size() -> None:
    evidence = FakeEvidenceProvider(
        overall={"claude_code": AgentPassportMetricBucket(execution_count=2, success_count=2)}
    )
    router = Router(evidence=evidence)
    decision = router.route(
        _request(), [_candidate("claude_code"), _candidate("codex")]
    )
    confidence = compute_confidence(decision)
    assert confidence is not None
    assert confidence.low_sample_size is True
    assert confidence.value < 0.5


def test_confidence_reflects_substantial_sample_and_clear_separation() -> None:
    evidence = FakeEvidenceProvider(
        overall={
            "claude_code": AgentPassportMetricBucket(execution_count=40, success_count=39),
            "codex": AgentPassportMetricBucket(execution_count=40, success_count=5),
        }
    )
    router = Router(evidence=evidence)
    decision = router.route(_request(), [_candidate("claude_code"), _candidate("codex")])
    confidence = compute_confidence(decision)
    assert confidence is not None
    assert confidence.low_sample_size is False
    assert confidence.value > 0.8


def test_confidence_reports_exact_tie_via_deterministic_tie_break() -> None:
    evidence = FakeEvidenceProvider(
        overall={
            "agent_a": AgentPassportMetricBucket(execution_count=10, success_count=8),
            "agent_b": AgentPassportMetricBucket(execution_count=10, success_count=8),
        }
    )
    router = Router(evidence=evidence)
    decision = router.route(_request(), [_candidate("agent_a"), _candidate("agent_b")])
    assert decision.selected_agent_type == "agent_a"
    confidence = compute_confidence(decision)
    assert confidence is not None
    assert "tied" in confidence.basis.lower()
    assert "tie-break" in confidence.basis.lower()


def test_confidence_for_single_eligible_candidate_has_no_separation_claim() -> None:
    evidence = FakeEvidenceProvider(
        overall={"claude_code": AgentPassportMetricBucket(execution_count=30, success_count=28)}
    )
    router = Router(evidence=evidence)
    decision = router.route(_request(), [_candidate("claude_code")])
    confidence = compute_confidence(decision)
    assert confidence is not None
    assert "only one eligible candidate" in confidence.basis.lower()


def test_confidence_is_none_for_manual_override() -> None:
    router = Router()
    decision = router.route(
        _request(manual_override_agent_type="claude_code"), [_candidate("claude_code")]
    )
    assert decision.manual_override is True
    assert compute_confidence(decision) is None


def test_confidence_is_none_when_no_candidate_selected() -> None:
    router = Router()
    decision = router.route(
        _request(required_capabilities=[AgentCapability.CODE_REVIEW]), [_candidate("claude_code")]
    )
    assert decision.selected_agent_type is None
    assert compute_confidence(decision) is None


def test_confidence_value_always_bounded_between_zero_and_one() -> None:
    evidence = FakeEvidenceProvider(
        overall={
            "claude_code": AgentPassportMetricBucket(execution_count=1000, success_count=999),
            "codex": AgentPassportMetricBucket(execution_count=0, success_count=0),
        }
    )
    router = Router(evidence=evidence)
    decision = router.route(_request(), [_candidate("claude_code"), _candidate("codex")])
    confidence = compute_confidence(decision)
    assert confidence is not None
    assert 0.0 <= confidence.value <= 1.0
