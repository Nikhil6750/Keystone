"""Tests for `app.engine.verification.recovery`: deterministic recovery
decisions and rerouting through the existing, unmodified Stage 4B `Router`."""

import inspect
from datetime import UTC, datetime
from typing import Any

import pytest

from app.contracts.adapter import AgentDescriptor
from app.contracts.enums import AgentCapability, AgentStatus, RuntimeKind
from app.contracts.routing import RoutingRequest
from app.contracts.verification import VerificationStatus
from app.engine.routing.availability import CandidateAgent
from app.engine.routing.router import Router
from app.engine.verification.aggregation import AggregatedVerification
from app.engine.verification.recovery import (
    RecoveryAction,
    RecoveryPolicy,
    build_reroute_request,
    decide_recovery,
    reroute,
)
from app.resilience.circuit_breaker import CircuitState

_NOW = datetime.now(UTC)


def _verification(status: VerificationStatus) -> AggregatedVerification:
    return AggregatedVerification(overall_status=status, checks=[], summary="x", created_at=_NOW)


def _candidate(agent_type: str, *, status: AgentStatus = AgentStatus.AVAILABLE) -> CandidateAgent:
    return CandidateAgent(
        descriptor=AgentDescriptor(
            agent_type=agent_type,
            display_name=agent_type,
            runtime_kind=RuntimeKind.AGENT_CLI,
            capabilities=[AgentCapability.CODE_GENERATION],
        ),
        status=status,
        circuit_state=CircuitState.CLOSED,
    )


def _request(**overrides: Any) -> RoutingRequest:
    base: dict[str, Any] = {"task_type": "code_generation"}
    base.update(overrides)
    return RoutingRequest.model_validate(base)


# --- decide_recovery -------------------------------------------------------------------


def test_accept_when_passed() -> None:
    decision = decide_recovery(
        verification=_verification(VerificationStatus.PASSED), attempt_number=1
    )
    assert decision.action is RecoveryAction.ACCEPT


def test_human_review_when_required_regardless_of_attempt_count() -> None:
    decision = decide_recovery(
        verification=_verification(VerificationStatus.REQUIRES_HUMAN_REVIEW),
        attempt_number=1,
        policy=RecoveryPolicy(max_attempts=1),
    )
    assert decision.action is RecoveryAction.HUMAN_REVIEW


def test_reroute_on_failure_when_allowed() -> None:
    decision = decide_recovery(
        verification=_verification(VerificationStatus.FAILED),
        attempt_number=1,
        policy=RecoveryPolicy(max_attempts=3, allow_reroute=True),
    )
    assert decision.action is RecoveryAction.REROUTE


def test_retry_same_when_reroute_disabled() -> None:
    decision = decide_recovery(
        verification=_verification(VerificationStatus.FAILED),
        attempt_number=1,
        policy=RecoveryPolicy(max_attempts=3, allow_reroute=False, allow_retry_same=True),
    )
    assert decision.action is RecoveryAction.RETRY_SAME


def test_request_consensus_once_due_and_allowed() -> None:
    decision = decide_recovery(
        verification=_verification(VerificationStatus.FAILED),
        attempt_number=2,
        policy=RecoveryPolicy(max_attempts=5, allow_consensus=True, consensus_after_attempts=2),
    )
    assert decision.action is RecoveryAction.REQUEST_CONSENSUS


def test_terminal_failure_when_max_attempts_reached() -> None:
    decision = decide_recovery(
        verification=_verification(VerificationStatus.FAILED),
        attempt_number=3,
        policy=RecoveryPolicy(max_attempts=3),
    )
    assert decision.action is RecoveryAction.FAIL


def test_terminal_failure_when_nothing_is_permitted() -> None:
    decision = decide_recovery(
        verification=_verification(VerificationStatus.FAILED),
        attempt_number=1,
        policy=RecoveryPolicy(
            max_attempts=5, allow_retry_same=False, allow_reroute=False, allow_consensus=False
        ),
    )
    assert decision.action is RecoveryAction.FAIL


def test_bounded_recovery_attempts_prevents_endless_reroute() -> None:
    policy = RecoveryPolicy(max_attempts=3, allow_reroute=True)
    verification = _verification(VerificationStatus.FAILED)
    actions = [
        decide_recovery(verification=verification, attempt_number=n, policy=policy).action
        for n in range(1, 6)
    ]
    assert actions[-1] is RecoveryAction.FAIL
    assert actions[2:] == [RecoveryAction.FAIL] * 3


def test_recovery_decision_rejects_attempt_number_below_one() -> None:
    with pytest.raises(ValueError, match="attempt_number"):
        decide_recovery(verification=_verification(VerificationStatus.FAILED), attempt_number=0)


def test_recovery_policy_rejects_max_attempts_below_one() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        RecoveryPolicy(max_attempts=0)


def test_recovery_decision_is_deterministic() -> None:
    verification = _verification(VerificationStatus.FAILED)
    policy = RecoveryPolicy(max_attempts=3)
    first = decide_recovery(verification=verification, attempt_number=1, policy=policy)
    for _ in range(20):
        again = decide_recovery(verification=verification, attempt_number=1, policy=policy)
        assert again.action == first.action
        assert again.reason == first.reason


def test_no_duplicate_stage_3_retry_semantics() -> None:
    """Structural guard: Stage 4E's recovery module must never *import* or
    *call* Stage 3's transient-execution retry machinery -- they operate at
    different layers and must never collide or duplicate each other. (The
    module docstring is allowed to *mention* `RetryingStepRunner` by name
    while explaining the separation -- this checks real imports/module
    attribute usage, not prose.)"""
    import app.engine.verification.recovery as recovery_module

    assert not hasattr(recovery_module, "RetryingStepRunner")
    assert not hasattr(recovery_module, "RetryPolicy")
    assert not hasattr(recovery_module, "CircuitBreakerRegistry")

    source = inspect.getsource(recovery_module)
    assert "RetryingStepRunner(" not in source
    assert "asyncio.sleep(" not in source


# --- rerouting --------------------------------------------------------------------------


def test_build_reroute_request_preserves_original_fields() -> None:
    original = _request(required_capabilities=[AgentCapability.CODE_GENERATION])
    rerouted = build_reroute_request(original, additionally_excluded_agent_types=["codex"])
    assert rerouted.task_type == original.task_type
    assert rerouted.required_capabilities == original.required_capabilities
    assert rerouted.repository == original.repository


def test_build_reroute_request_excludes_failed_agent_type() -> None:
    original = _request()
    rerouted = build_reroute_request(original, additionally_excluded_agent_types=["codex"])
    assert "codex" in rerouted.constraints.excluded_agent_types


def test_build_reroute_request_clears_manual_override() -> None:
    original = _request(manual_override_agent_type="codex")
    rerouted = build_reroute_request(original, additionally_excluded_agent_types=["codex"])
    assert rerouted.manual_override_agent_type is None


def test_reroute_excludes_the_failed_candidate() -> None:
    router = Router()
    candidates = [_candidate("claude_code"), _candidate("codex")]
    decision = reroute(
        router, _request(), candidates, additionally_excluded_agent_types=["codex"]
    )
    assert decision.selected_agent_type == "claude_code"
    excluded_scores = [c for c in decision.candidates if c.agent_type == "codex"]
    assert excluded_scores[0].eligible is False
    assert excluded_scores[0].excluded_reason is not None


def test_reroute_enforces_hard_constraints_not_just_exclusion() -> None:
    """A candidate lacking a required capability stays excluded on reroute
    too -- exclusion never bypasses other hard constraints."""
    router = Router()
    candidates = [
        _candidate("claude_code"),
        _candidate("codex"),
    ]
    request = _request(required_capabilities=[AgentCapability.CODE_REVIEW])
    decision = reroute(
        router, request, candidates, additionally_excluded_agent_types=["claude_code"]
    )
    assert decision.selected_agent_type is None  # neither declares CODE_REVIEW


def test_reroute_never_selects_an_explicitly_excluded_candidate() -> None:
    router = Router()
    candidates = [_candidate("claude_code"), _candidate("codex"), _candidate("gemini")]
    decision = reroute(
        router, _request(), candidates, additionally_excluded_agent_types=["claude_code", "codex"]
    )
    assert decision.selected_agent_type == "gemini"


def test_reroute_does_not_change_router_scoring_semantics() -> None:
    """Rerouting is a plain, unmodified `Router.route` call -- confirm the
    ordinary Router import path is used (no monkeypatching, no bypass)."""
    router = Router()
    candidates = [_candidate("claude_code"), _candidate("codex")]
    direct = router.route(
        build_reroute_request(_request(), additionally_excluded_agent_types=["codex"]), candidates
    )
    via_reroute = reroute(
        router, _request(), candidates, additionally_excluded_agent_types=["codex"]
    )
    assert direct.selected_agent_type == via_reroute.selected_agent_type
    direct_types = [c.agent_type for c in direct.candidates]
    via_reroute_types = [c.agent_type for c in via_reroute.candidates]
    assert direct_types == via_reroute_types


def test_reroute_is_deterministic() -> None:
    router = Router()
    candidates = [_candidate("claude_code"), _candidate("codex"), _candidate("gemini")]
    first = reroute(router, _request(), candidates, additionally_excluded_agent_types=["codex"])
    for _ in range(20):
        again = reroute(
            router, _request(), candidates, additionally_excluded_agent_types=["codex"]
        )
        assert again.selected_agent_type == first.selected_agent_type
        again_types = [c.agent_type for c in again.candidates]
        first_types = [c.agent_type for c in first.candidates]
        assert again_types == first_types
        again_scores = [c.composite_score for c in again.candidates]
        first_scores = [c.composite_score for c in first.candidates]
        assert again_scores == first_scores
