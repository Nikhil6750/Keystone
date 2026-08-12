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
from app.services.runtime_discovery import get_discovery_strategy

_DISPLAY_NAMES: dict[str, str] = {
    AgentType.CLAUDE_CODE.value: "Claude Code",
    AgentType.CODEX.value: "OpenAI Codex",
    AgentType.GEMINI.value: "Gemini CLI",
    AgentType.ANTIGRAVITY.value: "Google Antigravity",
    AgentType.DEMO.value: "Demo Agent",
}


def display_name_for(agent_type: str) -> str:
    return _DISPLAY_NAMES.get(agent_type, agent_type)


def capabilities_for(agent_type: str) -> list[str]:
    """Return a fresh API-safe capability list for one canonical agent type."""
    from app.engine.orchestration.runtime import STATIC_AGENT_DESCRIPTORS

    descriptor = STATIC_AGENT_DESCRIPTORS.get(agent_type)
    if descriptor is None:
        return []
    return [capability.value for capability in descriptor.capabilities]


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
    product_kind: str = "agent_cli"
    execution_supported: bool = True


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
    auth_status, connection_status, cached_version, last_checked_at = _cached_connection_fields(
        agent_type, cache
    )

    strategy = get_discovery_strategy(agent_type)
    if strategy:
        discovered = strategy.discover(configured_executable=profile.executable)
        installation_status = discovered.installation_status
        version = cached_version or discovered.version
        auth_status = (
            auth_status
            if auth_status != AuthenticationStatus.UNKNOWN
            else discovered.authentication_status
        )
        product_kind = discovered.product_kind
        execution_supported = discovered.execution_supported
        reason = discovered.reason
    else:
        product_kind = "agent_cli"
        execution_supported = True
        installed = shutil.which(profile.executable) is not None
        installation_status = (
            InstallationStatus.INSTALLED if installed else InstallationStatus.NOT_INSTALLED
        )
        version = cached_version
        reason = "Installed" if installed else "Executable not detected"

    if installation_status == InstallationStatus.INSTALLED:
        if not execution_supported:
            available = False
            enabled = False
            connection_status = ConnectionStatus.UNAVAILABLE
        else:
            available = True
            enabled = True
            if connection_status in (
                ConnectionStatus.DISABLED,
                ConnectionStatus.VERIFICATION_REQUIRED,
            ):
                if registered:
                    connection_status = ConnectionStatus.CONNECTED
                elif auth_status == AuthenticationStatus.AUTHENTICATED:
                    connection_status = ConnectionStatus.VERIFICATION_REQUIRED
                else:
                    connection_status = ConnectionStatus.UNAVAILABLE
    else:
        enabled = False
        available = False
        connection_status = ConnectionStatus.UNAVAILABLE
        reason = "Executable not detected"

    return AgentAvailability(
        agent_type=agent_type,
        display_name=display_name_for(agent_type),
        enabled=enabled,
        available=available,
        registered=registered,
        execution_mode="local_cli",
        reason=reason,
        installation_status=installation_status,
        authentication_status=auth_status,
        connection_status=connection_status,
        version=version,
        last_checked_at=last_checked_at,
        capabilities=capabilities_for(agent_type),
        product_kind=product_kind,
        execution_supported=execution_supported,
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
            product_kind="agent_cli",
            execution_supported=True,
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
            product_kind="simulation",
            execution_supported=True,
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
        product_kind="simulation",
        execution_supported=True,
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
