"""Shared, safe connection-state model and verification cache for local CLI
agent adapters (Claude Code, Codex, Google Antigravity).

Never reads a keyring, browser storage, or a credential file directly —
"authenticated" is only ever derived from a provider CLI's own official,
safe status command or from a harmless headless verification call actually
succeeding. Nothing here ever logs or persists a full provider response,
an email address, an org ID, or any other account-identifying detail.
"""

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable


class InstallationStatus(StrEnum):
    INSTALLED = "installed"
    NOT_INSTALLED = "not_installed"
    UNKNOWN = "unknown"


class AuthenticationStatus(StrEnum):
    AUTHENTICATED = "authenticated"
    UNAUTHENTICATED = "unauthenticated"
    UNKNOWN = "unknown"
    ERROR = "error"


class ConnectionStatus(StrEnum):
    CONNECTED = "connected"
    UNAVAILABLE = "unavailable"
    VERIFICATION_FAILED = "verification_failed"
    VERIFICATION_REQUIRED = "verification_required"
    DISABLED = "disabled"


@dataclass(frozen=True)
class AgentConnectionState:
    """A safe, API-facing snapshot of one provider's live connection state.

    "Connected" means a safe headless verification succeeded *recently*
    (within the cache window) — never merely that the executable exists.
    "Installed" is never labeled "connected". "Authenticated" is never
    inferred only from executable presence.
    """

    agent_type: str
    display_name: str
    executable_name: str
    enabled: bool
    installation_status: InstallationStatus
    authentication_status: AuthenticationStatus
    connection_status: ConnectionStatus
    registered: bool
    execution_mode: str
    version: str | None
    last_checked_at: datetime | None
    reason: str
    capabilities: list[str] = field(default_factory=list)


def new_verification_token(agent_type: str) -> str:
    """A fresh, unpredictable token for one verification call — never reused
    across calls, so a stale/cached provider response can never look like a
    fresh success."""
    return f"KEYSTONE_{agent_type.upper()}_VERIFY_{uuid.uuid4().hex[:12]}"


def build_verification_prompt(token: str) -> str:
    return (
        f"Reply with exactly {token}. Do not read files, inspect the "
        "repository, invoke tools, execute commands, access the network, "
        "or modify anything."
    )


@runtime_checkable
class ConnectionVerifier(Protocol):
    """What every provider adapter implements for Phase 6A.1 connection checks.

    `@runtime_checkable` so the availability/verification service can safely
    `isinstance()`-check a registered `AgentExecutor` before calling these
    methods — `DemoAgentAdapter` deliberately does not implement this
    protocol, since demo mode has no real connection to verify.
    """

    def detect(self) -> InstallationStatus:
        """Whether the configured executable resolves on `PATH`."""
        ...

    def read_version(self) -> str | None:
        """The installed CLI's own reported version string, or `None` if it
        could not be determined safely."""
        ...

    def check_authentication(self) -> AuthenticationStatus:
        """A safe, read-only authentication check — never a keyring read."""
        ...

    def verify_connection(self) -> tuple[ConnectionStatus, str]:
        """Run one harmless headless prompt with a fresh token and confirm
        the response contains exactly that token. Returns `(status, reason)`."""
        ...


class AgentConnectionCache:
    """Per-application, in-process cache of the last verification result per
    agent type, plus a simple in-process lock preventing two concurrent
    verifications for the same agent type.

    Never caches a secret or a full provider response — only the sanitized
    `AgentConnectionState`. Not a module-level singleton; one instance lives
    on `app.state`, exactly like `ExecutorRegistry`/`CircuitBreakerRegistry`.
    """

    def __init__(self, cache_seconds: float) -> None:
        self._cache_seconds = cache_seconds
        self._entries: dict[str, tuple[float, AgentConnectionState]] = {}
        self._in_progress: set[str] = set()

    def get(self, agent_type: str) -> AgentConnectionState | None:
        entry = self._entries.get(agent_type)
        if entry is None:
            return None
        recorded_at, state = entry
        if time.monotonic() - recorded_at > self._cache_seconds:
            return None
        return state

    def set(self, agent_type: str, state: AgentConnectionState) -> None:
        self._entries[agent_type] = (time.monotonic(), state)

    def try_begin_verification(self, agent_type: str) -> bool:
        """Returns `False` (without side effects) if a verification for this
        agent type is already running."""
        if agent_type in self._in_progress:
            return False
        self._in_progress.add(agent_type)
        return True

    def end_verification(self, agent_type: str) -> None:
        self._in_progress.discard(agent_type)


def now_utc() -> datetime:
    return datetime.now(UTC)
