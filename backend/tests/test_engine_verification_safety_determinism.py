"""Cross-cutting SAFETY and DETERMINISM tests for the Stage 4E verification
engine: no engine-layer type carries a credential/reasoning-shaped field
name, and the full verify -> aggregate -> recover -> reroute pipeline is
bit-for-bit repeatable given identical inputs."""

import dataclasses
from datetime import UTC, datetime
from typing import Any

from app.contracts.adapter import AgentDescriptor
from app.contracts.enums import AgentCapability, AgentStatus, BenchmarkEvaluatorType, RuntimeKind
from app.contracts.planning import ExpectedOutcome
from app.contracts.routing import RoutingRequest
from app.contracts.verification import VerificationStatus
from app.engine.routing.availability import CandidateAgent
from app.engine.routing.router import Router
from app.engine.verification.aggregation import AggregatedVerification, CheckOutcome
from app.engine.verification.consensus import ConsensusCandidate, ConsensusResult
from app.engine.verification.evaluators import (
    CommandExecutionOutcome,
    CommandSpec,
    EvaluatorOutcome,
    ObservedOutcome,
)
from app.engine.verification.recovery import (
    RecoveryDecision,
    RecoveryPolicy,
    decide_recovery,
    reroute,
)
from app.engine.verification.verifier import VerificationCheck, verify_many
from app.resilience.circuit_breaker import CircuitState

_NOW = datetime.now(UTC)

_FORBIDDEN_FIELD_NAME_SUBSTRINGS = (
    "password",
    "credential",
    "secret",
    "access_token",
    "session_token",
    "chain_of_thought",
    "reasoning",
    "internal_thought",
    "hidden_prompt",
    "raw_prompt",
    "scratchpad",
)

_ENGINE_DATACLASSES = (
    ObservedOutcome,
    EvaluatorOutcome,
    CommandSpec,
    CommandExecutionOutcome,
    CheckOutcome,
    AggregatedVerification,
    RecoveryPolicy,
    RecoveryDecision,
    VerificationCheck,
    ConsensusCandidate,
    ConsensusResult,
)


def test_no_engine_dataclass_has_a_credential_or_reasoning_shaped_field_name() -> None:
    offenders: list[str] = []
    for cls in _ENGINE_DATACLASSES:
        for f in dataclasses.fields(cls):
            lowered = f.name.lower()
            if any(bad in lowered for bad in _FORBIDDEN_FIELD_NAME_SUBSTRINGS):
                offenders.append(f"{cls.__name__}.{f.name}")
    assert offenders == []


def test_no_engine_dataclass_carries_an_environment_or_credential_dump_field() -> None:
    """`CommandSpec` in particular must never grow an `env`/`environment`
    field -- an injected executor must never be handed instructions to dump
    or override process environment/credentials."""
    field_names = {f.name for f in dataclasses.fields(CommandSpec)}
    assert "env" not in field_names
    assert "environment" not in field_names


# --- full-pipeline determinism ------------------------------------------------------


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


def _run_full_pipeline() -> tuple[str, str, str | None]:
    """verify -> aggregate -> decide_recovery -> (maybe) reroute, returning
    a small tuple of semantically meaningful fields for comparison."""
    checks = [
        VerificationCheck(
            expected=ExpectedOutcome(evaluator_type=BenchmarkEvaluatorType.EXIT_CODE, criteria={}),
            observed=ObservedOutcome({"exit_code": 1}),
        )
    ]
    verification = verify_many(
        checks, workflow_id="wf-1", verification_id_prefix="wf-1-v", created_at=_NOW
    )
    decision = decide_recovery(
        verification=verification, attempt_number=1, policy=RecoveryPolicy(max_attempts=3)
    )
    router = Router()
    candidates = [_candidate("claude_code"), _candidate("codex")]
    routing = reroute(
        router, _request(), candidates, additionally_excluded_agent_types=["claude_code"]
    )
    return verification.overall_status.value, decision.action.value, routing.selected_agent_type


def test_full_pipeline_identical_input_repeated_twenty_times_gives_identical_result() -> None:
    first = _run_full_pipeline()
    for _ in range(20):
        again = _run_full_pipeline()
        assert again == first


def test_recovery_decision_history_is_repeatable_across_twenty_runs() -> None:
    verification = AggregatedVerification(
        overall_status=VerificationStatus.FAILED, checks=[], summary="x", created_at=_NOW
    )
    policy = RecoveryPolicy(
        max_attempts=4, allow_reroute=True, allow_consensus=True, consensus_after_attempts=2
    )
    history = ["codex"]

    results = []
    for _ in range(20):
        decision = decide_recovery(
            verification=verification,
            attempt_number=2,
            policy=policy,
            previously_excluded_agent_types=history,
        )
        results.append((decision.action, decision.excluded_agent_types))
    assert len(set(results)) == 1
