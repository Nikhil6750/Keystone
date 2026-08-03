"""Performs one live connection verification for a single canonical agent type.

Only ever invoked by `POST /api/v1/agents/{agent_type}/verify` — never as a
side effect of `GET /api/v1/agents`, which always reads cached/last-known
state instead (see `agent_availability.py`).
"""

from app.adapters.connection import (
    AgentConnectionCache,
    AgentConnectionState,
    AuthenticationStatus,
    ConnectionStatus,
    ConnectionVerifier,
    InstallationStatus,
    now_utc,
)
from app.adapters.types import AgentType
from app.core.config import Settings
from app.engine.registry import ExecutorNotRegisteredError, ExecutorRegistry
from app.services.agent_availability import display_name_for

_CANONICAL_AGENT_TYPES = frozenset(item.value for item in AgentType)


class UnknownAgentTypeError(ValueError):
    """Raised when a caller requests verification of a non-canonical agent type."""

    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type
        super().__init__(f"'{agent_type}' is not a recognized canonical agent type")


class VerificationInProgressError(Exception):
    """Raised when a verification for this agent type is already running."""

    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type
        super().__init__(f"a verification for '{agent_type}' is already in progress")


def _profile_enabled(agent_type: str, settings: Settings) -> bool:
    factories = {
        AgentType.CLAUDE_CODE.value: settings.claude_code_profile,
        AgentType.CODEX.value: settings.codex_profile,
        AgentType.GEMINI.value: settings.gemini_profile,
        AgentType.ANTIGRAVITY.value: settings.antigravity_profile,
    }
    factory = factories.get(agent_type)
    if factory is None:
        return agent_type == AgentType.DEMO.value and settings.demo_enabled
    try:
        return factory().enabled
    except ValueError:
        return False


def verify_agent(
    agent_type: str,
    settings: Settings,
    registry: ExecutorRegistry,
    cache: AgentConnectionCache,
) -> AgentConnectionState:
    """Run one real, safe verification for `agent_type` and cache the result.

    Raises `UnknownAgentTypeError` for a non-canonical agent type, and
    `VerificationInProgressError` if a verification for the same agent type
    is already running. Never accepts a prompt from the caller — always uses
    the backend-owned harmless verification prompt.
    """
    if agent_type not in _CANONICAL_AGENT_TYPES:
        raise UnknownAgentTypeError(agent_type)

    if not cache.try_begin_verification(agent_type):
        raise VerificationInProgressError(agent_type)

    try:
        state = _run_verification(agent_type, settings, registry)
        cache.set(agent_type, state)
        return state
    finally:
        cache.end_verification(agent_type)


def _run_verification(
    agent_type: str, settings: Settings, registry: ExecutorRegistry
) -> AgentConnectionState:
    display_name = display_name_for(agent_type)
    enabled = _profile_enabled(agent_type, settings)

    if not enabled:
        return AgentConnectionState(
            agent_type=agent_type,
            display_name=display_name,
            executable_name="",
            enabled=False,
            installation_status=InstallationStatus.UNKNOWN,
            authentication_status=AuthenticationStatus.UNKNOWN,
            connection_status=ConnectionStatus.DISABLED,
            registered=False,
            execution_mode="demo" if agent_type == AgentType.DEMO.value else "local_cli",
            version=None,
            last_checked_at=now_utc(),
            reason="Disabled by configuration",
        )

    try:
        adapter = registry.get(agent_type)
    except ExecutorNotRegisteredError:
        return AgentConnectionState(
            agent_type=agent_type,
            display_name=display_name,
            executable_name="",
            enabled=True,
            installation_status=InstallationStatus.NOT_INSTALLED,
            authentication_status=AuthenticationStatus.UNKNOWN,
            connection_status=ConnectionStatus.UNAVAILABLE,
            registered=False,
            execution_mode="demo" if agent_type == AgentType.DEMO.value else "local_cli",
            version=None,
            last_checked_at=now_utc(),
            reason="No adapter is currently registered for this agent type",
        )

    if agent_type == AgentType.DEMO.value:
        return AgentConnectionState(
            agent_type=agent_type,
            display_name=display_name,
            executable_name="demo",
            enabled=True,
            installation_status=InstallationStatus.INSTALLED,
            authentication_status=AuthenticationStatus.AUTHENTICATED,
            connection_status=ConnectionStatus.CONNECTED,
            registered=True,
            execution_mode="demo",
            version=None,
            last_checked_at=now_utc(),
            reason="Demo mode requires no external connection",
        )

    if not isinstance(adapter, ConnectionVerifier):
        return AgentConnectionState(
            agent_type=agent_type,
            display_name=display_name,
            executable_name="",
            enabled=True,
            installation_status=InstallationStatus.UNKNOWN,
            authentication_status=AuthenticationStatus.UNKNOWN,
            connection_status=ConnectionStatus.VERIFICATION_FAILED,
            registered=True,
            execution_mode="local_cli",
            version=None,
            last_checked_at=now_utc(),
            reason="This adapter does not support connection verification",
        )

    installation_status = adapter.detect()
    if installation_status is not InstallationStatus.INSTALLED:
        return AgentConnectionState(
            agent_type=agent_type,
            display_name=display_name,
            executable_name="",
            enabled=True,
            installation_status=installation_status,
            authentication_status=AuthenticationStatus.UNKNOWN,
            connection_status=ConnectionStatus.UNAVAILABLE,
            registered=True,
            execution_mode="local_cli",
            version=None,
            last_checked_at=now_utc(),
            reason="Executable not found on PATH",
        )

    version = adapter.read_version()
    authentication_status = adapter.check_authentication()
    connection_status, reason = adapter.verify_connection()
    if connection_status is ConnectionStatus.CONNECTED and authentication_status in (
        AuthenticationStatus.UNKNOWN,
        AuthenticationStatus.UNAUTHENTICATED,
    ):
        # A successful headless response is itself positive proof of
        # authentication, even when the CLI's own status command couldn't
        # confirm it (or reported stale/unknown state).
        authentication_status = AuthenticationStatus.AUTHENTICATED
    elif (
        connection_status is not ConnectionStatus.CONNECTED
        and authentication_status is AuthenticationStatus.UNKNOWN
        and ("auth" in reason.lower() or "login" in reason.lower())
    ):
        authentication_status = AuthenticationStatus.ERROR

    return AgentConnectionState(
        agent_type=agent_type,
        display_name=display_name,
        executable_name="",
        enabled=True,
        installation_status=installation_status,
        authentication_status=authentication_status,
        connection_status=connection_status,
        registered=True,
        execution_mode="local_cli",
        version=version,
        last_checked_at=now_utc(),
        reason=reason,
    )
