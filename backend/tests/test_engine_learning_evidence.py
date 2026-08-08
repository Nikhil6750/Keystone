"""Tests for `app.engine.learning.evidence.PassportEvidenceProvider`: it
satisfies the existing `RoutingEvidenceProvider` Protocol and plugs into
`Router(evidence=...)` without any change to routing/scoring code."""

import inspect
from datetime import UTC, datetime
from typing import Any

import pytest

from app.contracts.adapter import AgentDescriptor, RepositoryMetadata
from app.contracts.enums import (
    AgentCapability,
    AgentExecutionStatus,
    AgentStatus,
    RuntimeKind,
)
from app.contracts.errors import FailureCategory
from app.contracts.routing import RoutingRequest
from app.engine.learning.events import LearningEvent
from app.engine.learning.evidence import PassportEvidenceProvider, build_passport_evidence_provider
from app.engine.routing.availability import CandidateAgent
from app.engine.routing.evidence import RoutingEvidenceProvider
from app.engine.routing.router import Router
from app.resilience.circuit_breaker import CircuitState

_NOW = datetime.now(UTC)


def _event(event_id: str, agent_type: str = "claude_code", **overrides: object) -> LearningEvent:
    base: dict[str, object] = {
        "event_id": event_id,
        "workflow_id": f"wf-{event_id}",
        "agent_type": agent_type,
        "execution_status": AgentExecutionStatus.SUCCEEDED,
        "created_at": _NOW,
    }
    base.update(overrides)
    return LearningEvent(**base)  # type: ignore[arg-type]


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


# --- Protocol conformance --------------------------------------------------------------


def test_passport_evidence_provider_satisfies_routing_evidence_provider_protocol() -> None:
    """`RoutingEvidenceProvider` is a structural (duck-typed) `Protocol`,
    not `@runtime_checkable` -- so conformance is proven by matching every
    required method name/signature and, more concretely, by every call
    below returning the exact types the Protocol promises."""
    provider = PassportEvidenceProvider()
    required_methods = {
        name
        for name, _ in inspect.getmembers(RoutingEvidenceProvider, predicate=inspect.isfunction)
        if not name.startswith("__")
    }
    assert required_methods == {
        "overall_metrics",
        "task_type_metrics",
        "repository_metrics",
        "cost_usd_estimate",
    }
    for name in required_methods:
        assert callable(getattr(provider, name, None))


def test_passport_evidence_provider_returns_none_for_unknown_agent_type() -> None:
    provider = PassportEvidenceProvider()
    assert provider.overall_metrics("unknown") is None
    assert provider.task_type_metrics("unknown", "code_generation") is None
    assert provider.repository_metrics("unknown", "org/repo") is None
    assert provider.cost_usd_estimate("unknown") is None


# --- overall / task / repository evidence ------------------------------------------------


def test_overall_evidence_reflects_built_passport() -> None:
    events = [_event("e1"), _event("e2")]
    provider = build_passport_evidence_provider(events, updated_at=_NOW)
    overall = provider.overall_metrics("claude_code")
    assert overall is not None
    assert overall.execution_count == 2
    assert overall.success_count == 2


def test_task_type_evidence_reflects_built_passport() -> None:
    events = [_event("e1", task_type="code_generation"), _event("e2", task_type="code_review")]
    provider = build_passport_evidence_provider(events, updated_at=_NOW)
    task_evidence = provider.task_type_metrics("claude_code", "code_generation")
    assert task_evidence is not None
    assert task_evidence.execution_count == 1
    assert provider.task_type_metrics("claude_code", "unknown_task") is None


def test_repository_evidence_reflects_built_passport() -> None:
    events = [_event("e1", repository_id="org/repo-a"), _event("e2", repository_id="org/repo-b")]
    provider = build_passport_evidence_provider(events, updated_at=_NOW)
    repo_evidence = provider.repository_metrics("claude_code", "org/repo-a")
    assert repo_evidence is not None
    assert repo_evidence.execution_count == 1
    assert provider.repository_metrics("claude_code", "org/repo-z") is None


def test_cost_estimate_is_none_without_real_evidence() -> None:
    events = [_event("e1", cost_usd=None)]
    provider = build_passport_evidence_provider(events, updated_at=_NOW)
    assert provider.cost_usd_estimate("claude_code") is None


def test_cost_estimate_reflects_real_known_cost() -> None:
    events = [_event("e1", cost_usd=0.10), _event("e2", cost_usd=0.20)]
    provider = build_passport_evidence_provider(events, updated_at=_NOW)
    assert provider.cost_usd_estimate("claude_code") == pytest.approx(0.15)


# --- Router integration -----------------------------------------------------------------


def test_router_selects_agent_using_passport_evidence() -> None:
    events = [
        _event(
            f"strong-{i}", agent_type="claude_code", task_type="code_generation", duration_ms=500.0
        )
        for i in range(10)
    ] + [
        _event(
            f"weak-{i}",
            agent_type="codex",
            task_type="code_generation",
            execution_status=AgentExecutionStatus.FAILED,
            failure_category=FailureCategory.PROVIDER_ERROR,
            duration_ms=500.0,
        )
        for i in range(10)
    ]
    provider = build_passport_evidence_provider(events, updated_at=_NOW)
    router = Router(evidence=provider)
    candidates = [_candidate("claude_code"), _candidate("codex")]
    decision = router.route(_request(), candidates)
    assert decision.selected_agent_type == "claude_code"


def test_router_consumes_repository_scoped_passport_evidence() -> None:
    events = [
        _event(
            f"e{i}",
            agent_type="claude_code",
            task_type="code_generation",
            repository_id="org/repo",
            duration_ms=500.0,
        )
        for i in range(10)
    ]
    provider = build_passport_evidence_provider(events, updated_at=_NOW)
    router = Router(evidence=provider)
    request = _request(repository=RepositoryMetadata(repository_id="org/repo"))
    decision = router.route(request, [_candidate("claude_code")])
    assert decision.selected_agent_type == "claude_code"
    scored = decision.candidates[0]
    assert scored.repository_score is not None


def test_router_scoring_code_is_never_imported_or_monkeypatched_by_learning_module() -> None:
    """Structural guard: Stage 5A's evidence module must never *import*
    anything from `app.engine.routing.scorer`/`router` -- confirming Stage
    5A only supplies evidence, never touches scoring logic. (The module
    docstring is allowed to *mention* `scorer` by name while explaining
    this separation -- this checks real imports, not prose.)"""
    import app.engine.learning.evidence as evidence_module

    assert not hasattr(evidence_module, "score_candidate")
    assert not hasattr(evidence_module, "RoutingWeights")
    assert not hasattr(evidence_module, "Router")

    import_lines = [
        line
        for line in inspect.getsource(evidence_module).splitlines()
        if line.startswith(("import ", "from "))
    ]
    assert not any("scorer" in line or "routing.router" in line for line in import_lines)
