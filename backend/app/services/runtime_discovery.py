r"""Generic, policy-driven runtime discovery strategies for supported AI agent runtimes.

Discovers local installations via:
1. Explicit user/settings override (if provided)
2. `shutil.which(executable)` on system `PATH`
3. Bounded, well-known platform installation directories (e.g. `%LOCALAPPDATA%\Programs\...`)

Safety guarantees:
- NEVER recursively scans the user's entire disk or home directory.
- NEVER executes arbitrary `.exe`, `.cmd`, or `.bat` files.
- NEVER hardcodes personal user paths (derives from OS environment variables).
- Version and authentication probes are strictly bounded read-only executions.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from app.adapters.connection import AuthenticationStatus, InstallationStatus
from app.adapters.process_runner import ProcessRunner, SubprocessRunner
from app.adapters.types import AgentType

_PROBE_TIMEOUT_SECONDS: Final[float] = 5.0
_PROBE_MAX_OUTPUT_CHARS: Final[int] = 4000


@dataclass(frozen=True)
class DiscoveredRuntimeInfo:
    """Truthful discovery report for one runtime identity."""

    runtime_type: str
    display_name: str
    product_kind: str  # "agent_cli" | "ide" | "simulation"
    execution_supported: bool
    installation_status: InstallationStatus
    executable_path: str | None
    version: str | None
    authentication_status: AuthenticationStatus
    supports_sign_in: bool
    reason: str


@runtime_checkable
class RuntimeDiscoveryStrategy(Protocol):
    """Protocol implemented by every runtime discovery provider."""

    @property
    def runtime_type(self) -> str: ...

    @property
    def display_name(self) -> str: ...

    @property
    def product_kind(self) -> str: ...

    @property
    def execution_supported(self) -> bool: ...

    @property
    def supports_sign_in(self) -> bool: ...

    def find_executable(self, configured_executable: str | None = None) -> str | None: ...

    def probe_version(
        self, executable_path: str, runner: ProcessRunner | None = None
    ) -> str | None: ...

    def probe_authentication(
        self, executable_path: str, runner: ProcessRunner | None = None
    ) -> AuthenticationStatus: ...

    def discover(
        self, configured_executable: str | None = None, runner: ProcessRunner | None = None
    ) -> DiscoveredRuntimeInfo: ...


def _bounded_run(
    executable_path: str, args: Sequence[str], runner: ProcessRunner | None = None
) -> str | None:
    runner_impl = runner or SubprocessRunner()
    try:
        res = runner_impl.run(
            executable_path,
            list(args),
            stdin_text=None,
            timeout_seconds=_PROBE_TIMEOUT_SECONDS,
            max_output_characters=_PROBE_MAX_OUTPUT_CHARS,
        )
        if res.exit_code == 0:
            return (res.stdout or res.stderr or "").strip()
        return None
    except Exception:  # noqa: BLE001
        return None


class BaseRuntimeDiscoveryStrategy:
    """Base class providing default bounded search & probing behaviors."""

    def __init__(
        self,
        runtime_type: str,
        display_name: str,
        default_binary: str,
        candidate_subpaths: Sequence[tuple[str, ...]] = (),
        product_kind: str = "agent_cli",
        execution_supported: bool = True,
        supports_sign_in: bool = True,
    ) -> None:
        self._runtime_type = runtime_type
        self._display_name = display_name
        self._default_binary = default_binary
        self._candidate_subpaths = candidate_subpaths
        self._product_kind = product_kind
        self._execution_supported = execution_supported
        self._supports_sign_in = supports_sign_in

    @property
    def runtime_type(self) -> str:
        return self._runtime_type

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def product_kind(self) -> str:
        return self._product_kind

    @property
    def execution_supported(self) -> bool:
        return self._execution_supported

    @property
    def supports_sign_in(self) -> bool:
        return self._supports_sign_in

    def find_executable(self, configured_executable: str | None = None) -> str | None:
        # 1. User-configured override or direct path
        if configured_executable:
            resolved = shutil.which(configured_executable)
            if resolved:
                return resolved
            if Path(configured_executable).is_file():
                return str(Path(configured_executable).resolve())

        # 2. Check system PATH
        resolved = shutil.which(self._default_binary)
        if resolved:
            return resolved

        # 3. Check well-known Windows install directories (derived dynamically from ENV)
        root_dirs: list[Path] = []
        for env_var in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "APPDATA"):
            val = os.environ.get(env_var)
            if val:
                root_dirs.append(Path(val))

        for root in root_dirs:
            for subpath in self._candidate_subpaths:
                candidate = root.joinpath(*subpath)
                if candidate.is_file():
                    return str(candidate.resolve())

        return None

    def probe_version(
        self, executable_path: str, runner: ProcessRunner | None = None
    ) -> str | None:
        output = _bounded_run(executable_path, ["--version"], runner)
        if output:
            first_line = output.splitlines()[0].strip()
            return first_line[:100]
        return None

    def probe_authentication(
        self, executable_path: str, runner: ProcessRunner | None = None
    ) -> AuthenticationStatus:
        return AuthenticationStatus.UNKNOWN

    def discover(
        self, configured_executable: str | None = None, runner: ProcessRunner | None = None
    ) -> DiscoveredRuntimeInfo:
        exe = self.find_executable(configured_executable)
        if not exe:
            return DiscoveredRuntimeInfo(
                runtime_type=self.runtime_type,
                display_name=self.display_name,
                product_kind=self.product_kind,
                execution_supported=self.execution_supported,
                installation_status=InstallationStatus.NOT_INSTALLED,
                executable_path=None,
                version=None,
                authentication_status=AuthenticationStatus.UNKNOWN,
                supports_sign_in=self.supports_sign_in,
                reason="Executable not detected on PATH or well-known locations",
            )

        version = self.probe_version(exe, runner)
        auth = self.probe_authentication(exe, runner)

        if not self.execution_supported:
            reason = f"{self.product_kind.upper()} detected (Execution adapter unavailable)"
        elif auth == AuthenticationStatus.AUTHENTICATED:
            reason = "Installed and authenticated"
        elif auth == AuthenticationStatus.UNAUTHENTICATED:
            reason = "Installed (sign in required)"
        else:
            reason = "Installed"

        return DiscoveredRuntimeInfo(
            runtime_type=self.runtime_type,
            display_name=self.display_name,
            product_kind=self.product_kind,
            execution_supported=self.execution_supported,
            installation_status=InstallationStatus.INSTALLED,
            executable_path=exe,
            version=version,
            authentication_status=auth,
            supports_sign_in=self.supports_sign_in,
            reason=reason,
        )


class ClaudeCodeDiscoveryStrategy(BaseRuntimeDiscoveryStrategy):
    def __init__(self) -> None:
        super().__init__(
            runtime_type=AgentType.CLAUDE_CODE.value,
            display_name="Claude Code",
            default_binary="claude",
            candidate_subpaths=[
                ("npm", "claude.cmd"),
                ("npm", "claude"),
            ],
            product_kind="agent_cli",
            execution_supported=True,
            supports_sign_in=True,
        )

    def probe_authentication(
        self, executable_path: str, runner: ProcessRunner | None = None
    ) -> AuthenticationStatus:
        out = _bounded_run(executable_path, ["auth", "status"], runner)
        if out:
            lower = out.lower()
            if "logged in" in lower or "authenticated" in lower or "true" in lower:
                return AuthenticationStatus.AUTHENTICATED
            if "not logged in" in lower or "unauthenticated" in lower:
                return AuthenticationStatus.UNAUTHENTICATED
        return AuthenticationStatus.UNKNOWN


class CodexDiscoveryStrategy(BaseRuntimeDiscoveryStrategy):
    def __init__(self) -> None:
        super().__init__(
            runtime_type=AgentType.CODEX.value,
            display_name="OpenAI Codex",
            default_binary="codex",
            candidate_subpaths=[
                ("Programs", "OpenAI", "Codex", "bin", "codex.exe"),
                ("Programs", "OpenAI", "Codex", "bin", "codex"),
                ("npm", "codex.cmd"),
            ],
            product_kind="agent_cli",
            execution_supported=True,
            supports_sign_in=True,
        )

    def probe_authentication(
        self, executable_path: str, runner: ProcessRunner | None = None
    ) -> AuthenticationStatus:
        out = _bounded_run(executable_path, ["login", "status"], runner)
        if out:
            lower = out.lower()
            if "logged in" in lower and "not logged in" not in lower:
                return AuthenticationStatus.AUTHENTICATED
            if "not logged in" in lower:
                return AuthenticationStatus.UNAUTHENTICATED
        return AuthenticationStatus.UNKNOWN


class AntigravityDiscoveryStrategy(BaseRuntimeDiscoveryStrategy):
    """Google Antigravity IDE launcher & agy CLI discovery strategy."""

    def __init__(self) -> None:
        super().__init__(
            runtime_type=AgentType.ANTIGRAVITY.value,
            display_name="Google Antigravity",
            default_binary="antigravity-ide",
            candidate_subpaths=[
                ("npm", "agy.cmd"),
                ("npm", "agy"),
                ("Programs", "Antigravity IDE", "bin", "antigravity-ide.cmd"),
                ("Programs", "Antigravity IDE", "Antigravity IDE.exe"),
                ("Programs", "antigravity", "antigravity.exe"),
            ],
            product_kind="agent_cli",
            execution_supported=True,
            supports_sign_in=False,
        )

    def discover(
        self, configured_executable: str | None = None, runner: ProcessRunner | None = None
    ) -> DiscoveredRuntimeInfo:
        exe = self.find_executable(configured_executable)
        if not exe:
            return DiscoveredRuntimeInfo(
                runtime_type=self.runtime_type,
                display_name=self.display_name,
                product_kind=self.product_kind,
                execution_supported=self.execution_supported,
                installation_status=InstallationStatus.NOT_INSTALLED,
                executable_path=None,
                version=None,
                authentication_status=AuthenticationStatus.UNKNOWN,
                supports_sign_in=self.supports_sign_in,
                reason="Executable not detected on PATH or well-known locations",
            )

        exe_lower = exe.lower()
        is_ide_launcher = "ide" in exe_lower or "antigravity.exe" in exe_lower
        is_agy_cli = "agy" in exe_lower or exe_lower == "mock" or not is_ide_launcher

        product_kind = "agent_cli" if is_agy_cli else "ide"
        execution_supported = is_agy_cli

        version = self.probe_version(exe, runner)
        auth = self.probe_authentication(exe, runner)

        if not execution_supported:
            reason = f"{product_kind.upper()} detected (Execution adapter unavailable)"
        elif auth == AuthenticationStatus.AUTHENTICATED:
            reason = "Installed and authenticated"
        else:
            reason = "Installed"

        return DiscoveredRuntimeInfo(
            runtime_type=self.runtime_type,
            display_name=self.display_name,
            product_kind=product_kind,
            execution_supported=execution_supported,
            installation_status=InstallationStatus.INSTALLED,
            executable_path=exe,
            version=version,
            authentication_status=auth,
            supports_sign_in=self.supports_sign_in,
            reason=reason,
        )


class GeminiDiscoveryStrategy(BaseRuntimeDiscoveryStrategy):
    """Gemini CLI separate runtime discovery strategy."""

    def __init__(self) -> None:
        super().__init__(
            runtime_type=AgentType.GEMINI.value,
            display_name="Gemini CLI",
            default_binary="gemini",
            candidate_subpaths=[
                ("npm", "gemini.cmd"),
                ("npm", "gemini"),
            ],
            product_kind="agent_cli",
            execution_supported=True,
            supports_sign_in=True,
        )


class DemoDiscoveryStrategy(BaseRuntimeDiscoveryStrategy):
    def __init__(self) -> None:
        super().__init__(
            runtime_type=AgentType.DEMO.value,
            display_name="Demo Agent",
            default_binary="demo",
            product_kind="simulation",
            execution_supported=True,
            supports_sign_in=False,
        )

    def find_executable(self, configured_executable: str | None = None) -> str | None:
        return "demo"

    def probe_version(
        self, executable_path: str, runner: ProcessRunner | None = None
    ) -> str | None:
        return "1.0.0-demo"

    def probe_authentication(
        self, executable_path: str, runner: ProcessRunner | None = None
    ) -> AuthenticationStatus:
        return AuthenticationStatus.AUTHENTICATED


_STRATEGIES: dict[str, BaseRuntimeDiscoveryStrategy] = {
    AgentType.CLAUDE_CODE.value: ClaudeCodeDiscoveryStrategy(),
    AgentType.CODEX.value: CodexDiscoveryStrategy(),
    AgentType.ANTIGRAVITY.value: AntigravityDiscoveryStrategy(),
    AgentType.GEMINI.value: GeminiDiscoveryStrategy(),
    AgentType.DEMO.value: DemoDiscoveryStrategy(),
}


def get_discovery_strategy(agent_type: str) -> BaseRuntimeDiscoveryStrategy | None:
    return _STRATEGIES.get(agent_type)


def list_discovery_strategies() -> list[BaseRuntimeDiscoveryStrategy]:
    return list(_STRATEGIES.values())


__all__ = [
    "AntigravityDiscoveryStrategy",
    "BaseRuntimeDiscoveryStrategy",
    "ClaudeCodeDiscoveryStrategy",
    "CodexDiscoveryStrategy",
    "DemoDiscoveryStrategy",
    "DiscoveredRuntimeInfo",
    "GeminiDiscoveryStrategy",
    "RuntimeDiscoveryStrategy",
    "get_discovery_strategy",
    "list_discovery_strategies",
]
