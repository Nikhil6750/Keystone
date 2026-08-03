"""Reports configuration/availability/registration status for each canonical agent type."""

import shutil
from collections.abc import Callable
from dataclasses import dataclass

from app.adapters.types import AgentType, CLIProfile
from app.core.config import Settings
from app.engine.registry import ExecutorNotRegisteredError, ExecutorRegistry


@dataclass(frozen=True)
class AgentAvailability:
    """A safe, API-facing availability report for one canonical agent type."""

    agent_type: str
    enabled: bool
    available: bool
    registered: bool
    execution_mode: str
    reason: str


def _is_registered(registry: ExecutorRegistry, agent_type: str) -> bool:
    try:
        registry.get(agent_type)
    except ExecutorNotRegisteredError:
        return False
    return True


def _cli_availability(
    agent_type: str, profile: CLIProfile, registry: ExecutorRegistry
) -> AgentAvailability:
    registered = _is_registered(registry, agent_type)
    if not profile.enabled:
        return AgentAvailability(
            agent_type=agent_type,
            enabled=False,
            available=False,
            registered=registered,
            execution_mode="local_cli",
            reason="Disabled by configuration",
        )
    if shutil.which(profile.executable) is None:
        return AgentAvailability(
            agent_type=agent_type,
            enabled=True,
            available=False,
            registered=registered,
            execution_mode="local_cli",
            reason="Executable not found on PATH",
        )
    return AgentAvailability(
        agent_type=agent_type,
        enabled=True,
        available=True,
        registered=registered,
        execution_mode="local_cli",
        reason="Enabled and executable resolved",
    )


def _safe_cli_availability(
    agent_type: str, profile_factory: Callable[[], CLIProfile], registry: ExecutorRegistry
) -> AgentAvailability:
    try:
        profile = profile_factory()
    except ValueError:
        return AgentAvailability(
            agent_type=agent_type,
            enabled=False,
            available=False,
            registered=_is_registered(registry, agent_type),
            execution_mode="local_cli",
            reason="Invalid configuration",
        )
    return _cli_availability(agent_type, profile, registry)


def _demo_availability(settings: Settings, registry: ExecutorRegistry) -> AgentAvailability:
    registered = _is_registered(registry, AgentType.DEMO.value)
    if not settings.demo_enabled:
        return AgentAvailability(
            agent_type=AgentType.DEMO.value,
            enabled=False,
            available=False,
            registered=registered,
            execution_mode="demo",
            reason="Disabled by configuration",
        )
    return AgentAvailability(
        agent_type=AgentType.DEMO.value,
        enabled=True,
        available=True,
        registered=registered,
        execution_mode="demo",
        reason="Enabled",
    )


def list_agent_availability(
    settings: Settings, registry: ExecutorRegistry
) -> list[AgentAvailability]:
    """Report availability for all four canonical agent types, in stable order."""
    return [
        _safe_cli_availability(AgentType.CLAUDE_CODE.value, settings.claude_code_profile, registry),
        _safe_cli_availability(AgentType.CODEX.value, settings.codex_profile, registry),
        _safe_cli_availability(AgentType.GEMINI.value, settings.gemini_profile, registry),
        _demo_availability(settings, registry),
    ]
