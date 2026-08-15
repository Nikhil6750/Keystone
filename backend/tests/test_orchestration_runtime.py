"""Tests for `app.engine.orchestration.runtime`."""

import pytest

from app.adapters.connection import (
    AgentConnectionCache,
    AgentConnectionState,
    AuthenticationStatus,
    ConnectionStatus,
    InstallationStatus,
)
from app.contracts.enums import AgentStatus
from app.engine.orchestration.runtime import (
    STATIC_AGENT_DESCRIPTORS,
    RegistryCandidateProvider,
    StaticCandidateProvider,
)
from app.engine.registry import ExecutorRegistry
from app.resilience.circuit_breaker import CircuitBreakerRegistry, CircuitState
from tests.support.executors import RecordingExecutor
from tests.support.orchestration_fakes import build_candidate


def test_static_candidate_provider_returns_configured_agents() -> None:
    candidate = build_candidate("claude_code")
    provider = StaticCandidateProvider(agents=(candidate,))
    assert provider.candidates() == [candidate]


def test_static_candidate_provider_never_touches_network(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import socket

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("StaticCandidateProvider must never open a socket")

    monkeypatch.setattr(socket, "socket", _forbidden)
    provider = StaticCandidateProvider(agents=(build_candidate("claude_code"),))
    assert len(provider.candidates()) == 1


def test_registry_candidate_provider_skips_unregistered_agent_types() -> None:
    registry = ExecutorRegistry()
    registry.register("claude_code", RecordingExecutor())
    provider = RegistryCandidateProvider(registry=registry, agent_types=("claude_code", "codex"))
    candidates = provider.candidates()
    assert [c.descriptor.agent_type for c in candidates] == ["claude_code"]


def test_registry_candidate_provider_skips_unknown_descriptor() -> None:
    registry = ExecutorRegistry()
    registry.register("totally_unknown_agent", RecordingExecutor())
    provider = RegistryCandidateProvider(registry=registry, agent_types=("totally_unknown_agent",))
    assert provider.candidates() == []


def test_registry_candidate_provider_status_unknown_without_connection_cache() -> None:
    registry = ExecutorRegistry()
    registry.register("claude_code", RecordingExecutor())
    provider = RegistryCandidateProvider(registry=registry, agent_types=("claude_code",))
    candidates = provider.candidates()
    assert candidates[0].status == AgentStatus.UNKNOWN


def test_registry_candidate_provider_reads_connected_status_from_cache() -> None:
    registry = ExecutorRegistry()
    registry.register("claude_code", RecordingExecutor())
    cache = AgentConnectionCache(cache_seconds=60.0)
    cache.set(
        "claude_code",
        AgentConnectionState(
            agent_type="claude_code",
            display_name="Claude Code",
            executable_name="claude",
            enabled=True,
            installation_status=InstallationStatus.INSTALLED,
            authentication_status=AuthenticationStatus.AUTHENTICATED,
            connection_status=ConnectionStatus.CONNECTED,
            registered=True,
            execution_mode="cli",
            version="1.0.0",
            last_checked_at=None,
            reason="ok",
        ),
    )
    provider = RegistryCandidateProvider(
        registry=registry, agent_types=("claude_code",), connection_cache=cache
    )
    candidates = provider.candidates()
    assert candidates[0].status == AgentStatus.AVAILABLE


@pytest.mark.parametrize(
    ("overrides"),
    [
        {"enabled": False},
        {"registered": False},
        {"installation_status": InstallationStatus.NOT_INSTALLED},
        {"authentication_status": AuthenticationStatus.UNAUTHENTICATED},
    ],
)
def test_connected_label_cannot_override_unusable_runtime_state(
    overrides: dict[str, object],
) -> None:
    registry = ExecutorRegistry()
    registry.register("claude_code", RecordingExecutor())
    cache = AgentConnectionCache(cache_seconds=60.0)
    state_fields: dict[str, object] = {
        "agent_type": "claude_code",
        "display_name": "Claude Code",
        "executable_name": "claude",
        "enabled": True,
        "installation_status": InstallationStatus.INSTALLED,
        "authentication_status": AuthenticationStatus.AUTHENTICATED,
        "connection_status": ConnectionStatus.CONNECTED,
        "registered": True,
        "execution_mode": "cli",
        "version": "1.0.0",
        "last_checked_at": None,
        "reason": "malformed cached state",
    }
    state_fields.update(overrides)
    cache.set("claude_code", AgentConnectionState(**state_fields))  # type: ignore[arg-type]

    provider = RegistryCandidateProvider(
        registry=registry, agent_types=("claude_code",), connection_cache=cache
    )
    assert provider.candidates()[0].status == AgentStatus.UNAVAILABLE


def test_registry_candidate_provider_reads_circuit_state() -> None:
    registry = ExecutorRegistry()
    registry.register("claude_code", RecordingExecutor())
    breakers = CircuitBreakerRegistry(failure_threshold=1, recovery_timeout_seconds=60.0)
    breaker = breakers.get_or_create("claude_code")
    breaker.before_call()
    breaker.record_failure()
    provider = RegistryCandidateProvider(
        registry=registry, agent_types=("claude_code",), circuit_breakers=breakers
    )
    candidates = provider.candidates()
    assert candidates[0].circuit_state == CircuitState.OPEN


def test_static_agent_descriptors_cover_known_agent_types() -> None:
    assert "claude_code" in STATIC_AGENT_DESCRIPTORS
    assert "codex" in STATIC_AGENT_DESCRIPTORS
    assert "demo" in STATIC_AGENT_DESCRIPTORS
    for agent_type, descriptor in STATIC_AGENT_DESCRIPTORS.items():
        assert descriptor.agent_type == agent_type
