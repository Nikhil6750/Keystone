"""Reports configuration/availability/connection status for each canonical agent type.

`GET /api/v1/agents` always returns instantly from cached/last-known state —
live verification (an actual headless CLI call) only ever happens through
the explicit `POST /agents/{agent_type}/verify` endpoint, never as a side
effect of listing agents.
"""

import shutil
from collections.abc import Callable
from dataclasses import dataclass, field

from app.adapters.connection import (
    AgentConnectionCache,
    AuthenticationStatus,
    ConnectionStatus,
    InstallationStatus,
)
from app.adapters.types import AgentType, CLIProfile
from app.core.config import Settings
from app.engine.registry import ExecutorNotRegisteredError, ExecutorRegistry

_DISPLAY_NAMES: dict[str, str] = {
    AgentType.CLAUDE_CODE.value: "Claude Code",
    AgentType.CODEX.value: "OpenAI Codex",
    AgentType.GEMINI.value: "Gemini CLI",
    AgentType.ANTIGRAVITY.value: "Google Antigravity",
    AgentType.DEMO.value: "Demo Agent",
}

_CAPABILITIES: dict[str, list[str]] = {
    AgentType.CLAUDE_CODE.value: ["workflow_step_execution"],
    AgentType.CODEX.value: ["workflow_step_execution"],
    AgentType.GEMINI.value: [],
    AgentType.ANTIGRAVITY.value: ["workflow_step_execution"],
    AgentType.DEMO.value: ["workflow_step_execution"],
}


def display_name_for(agent_type: str) -> str:
    return _DISPLAY_NAMES.get(agent_type, agent_type)


def capabilities_for(agent_type: str) -> list[str]:
    """Return a fresh API-safe capability list for one canonical agent type."""
    return list(_CAPABILITIES.get(agent_type, []))


@dataclass(frozen=True)
class AgentAvailability:
    """A safe, API-facing availability + connection report for one canonical agent type."""

    agent_type: str
    display_name: str
    enabled: bool
    available: bool
    registered: bool
    execution_mode: str
    reason: str
    installation_status: InstallationStatus
    authentication_status: AuthenticationStatus
    connection_status: ConnectionStatus
    version: str | None
    last_checked_at: str | None
    capabilities: list[str] = field(default_factory=list)


def _is_registered(registry: ExecutorRegistry, agent_type: str) -> bool:
    try:
        registry.get(agent_type)
    except ExecutorNotRegisteredError:
        return False
    return True


def _cached_connection_fields(
    agent_type: str, cache: AgentConnectionCache | None
) -> tuple[AuthenticationStatus, ConnectionStatus, str | None, str | None]:
    if cache is None:
        return (
            AuthenticationStatus.UNKNOWN,
            ConnectionStatus.VERIFICATION_REQUIRED,
            None,
            None,
        )
    cached = cache.get(agent_type)
    if cached is None:
        return (
            AuthenticationStatus.UNKNOWN,
            ConnectionStatus.VERIFICATION_REQUIRED,
            None,
            None,
        )
    return (
        cached.authentication_status,
        cached.connection_status,
        cached.version,
        cached.last_checked_at.isoformat() if cached.last_checked_at else None,
    )


def _cli_availability(
    agent_type: str,
    profile: CLIProfile,
    registry: ExecutorRegistry,
    cache: AgentConnectionCache | None,
) -> AgentAvailability:
    registered = _is_registered(registry, agent_type)
    auth_status, connection_status, version, last_checked_at = _cached_connection_fields(
        agent_type, cache
    )

    if not profile.enabled:
        return AgentAvailability(
            agent_type=agent_type,
            display_name=display_name_for(agent_type),
            enabled=False,
            available=False,
            registered=registered,
            execution_mode="local_cli",
            reason="Disabled by configuration",
            installation_status=InstallationStatus.UNKNOWN,
            authentication_status=AuthenticationStatus.UNKNOWN,
            connection_status=ConnectionStatus.DISABLED,
            version=None,
            last_checked_at=None,
            capabilities=capabilities_for(agent_type),
        )

    installed = shutil.which(profile.executable) is not None
    if not installed:
        return AgentAvailability(
            agent_type=agent_type,
            display_name=display_name_for(agent_type),
            enabled=True,
            available=False,
            registered=registered,
            execution_mode="local_cli",
            reason="Executable not found on PATH",
            installation_status=InstallationStatus.NOT_INSTALLED,
            authentication_status=AuthenticationStatus.UNKNOWN,
            connection_status=ConnectionStatus.UNAVAILABLE,
            version=None,
            last_checked_at=None,
            capabilities=capabilities_for(agent_type),
        )

    return AgentAvailability(
        agent_type=agent_type,
        display_name=display_name_for(agent_type),
        enabled=True,
        available=True,
        registered=registered,
        execution_mode="local_cli",
        reason="Enabled and executable resolved",
        installation_status=InstallationStatus.INSTALLED,
        authentication_status=auth_status,
        connection_status=connection_status,
        version=version,
        last_checked_at=last_checked_at,
        capabilities=capabilities_for(agent_type),
    )


def _safe_cli_availability(
    agent_type: str,
    profile_factory: Callable[[], CLIProfile],
    registry: ExecutorRegistry,
    cache: AgentConnectionCache | None,
) -> AgentAvailability:
    try:
        profile = profile_factory()
    except ValueError:
        return AgentAvailability(
            agent_type=agent_type,
            display_name=display_name_for(agent_type),
            enabled=False,
            available=False,
            registered=_is_registered(registry, agent_type),
            execution_mode="local_cli",
            reason="Invalid configuration",
            installation_status=InstallationStatus.UNKNOWN,
            authentication_status=AuthenticationStatus.UNKNOWN,
            connection_status=ConnectionStatus.DISABLED,
            version=None,
            last_checked_at=None,
            capabilities=capabilities_for(agent_type),
        )
    return _cli_availability(agent_type, profile, registry, cache)


def _demo_availability(settings: Settings, registry: ExecutorRegistry) -> AgentAvailability:
    registered = _is_registered(registry, AgentType.DEMO.value)
    if not settings.demo_enabled:
        return AgentAvailability(
            agent_type=AgentType.DEMO.value,
            display_name=display_name_for(AgentType.DEMO.value),
            enabled=False,
            available=False,
            registered=registered,
            execution_mode="demo",
            reason="Disabled by configuration",
            installation_status=InstallationStatus.UNKNOWN,
            authentication_status=AuthenticationStatus.UNKNOWN,
            connection_status=ConnectionStatus.DISABLED,
            version=None,
            last_checked_at=None,
            capabilities=capabilities_for(AgentType.DEMO.value),
        )
    return AgentAvailability(
        agent_type=AgentType.DEMO.value,
        display_name=display_name_for(AgentType.DEMO.value),
        enabled=True,
        available=True,
        registered=registered,
        execution_mode="demo",
        reason="Enabled",
        installation_status=InstallationStatus.INSTALLED,
        authentication_status=AuthenticationStatus.AUTHENTICATED,
        connection_status=(
            ConnectionStatus.CONNECTED if registered else ConnectionStatus.UNAVAILABLE
        ),
        version=None,
        last_checked_at=None,
        capabilities=capabilities_for(AgentType.DEMO.value),
    )


def list_agent_availability(
    settings: Settings,
    registry: ExecutorRegistry,
    cache: AgentConnectionCache | None = None,
) -> list[AgentAvailability]:
    """Report availability/connection status for every canonical agent type, in stable order."""
    return [
        _safe_cli_availability(
            AgentType.CLAUDE_CODE.value, settings.claude_code_profile, registry, cache
        ),
        _safe_cli_availability(AgentType.CODEX.value, settings.codex_profile, registry, cache),
        _safe_cli_availability(
            AgentType.ANTIGRAVITY.value, settings.antigravity_profile, registry, cache
        ),
        _safe_cli_availability(AgentType.GEMINI.value, settings.gemini_profile, registry, cache),
        _demo_availability(settings, registry),
    ]
