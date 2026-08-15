"""Safe, defensive process execution boundary for Stage 9D Quality Gate Executors.

Security Invariants:
1. `shell=False` unconditionally -- argv-only execution.
2. Approved executable allow-list (`ALLOWED_QUALITY_EXECUTABLES`).
3. Enforced bounded timeout per execution.
4. Bounded stdout/stderr capture (no memory exhaustion).
5. Strict workspace path containment (rejects directory traversal and path escapes).
6. Sanitized safe environment (no credential, token, or secret leaks).
7. Rejects arbitrary unapproved commands from model outputs.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from app.engine.quality.errors import (
    QualitySecurityError,
    UnapprovedQualityCommandError,
)

MAX_OUTPUT_CHARACTERS: Final = 20_000

# Strict allowlist of approved executables for software quality verification
ALLOWED_QUALITY_EXECUTABLES: Final = frozenset(
    {
        "python",
        "python.exe",
        "pytest",
        "pytest.exe",
        "ruff",
        "ruff.exe",
        "mypy",
        "mypy.exe",
        "node",
        "node.exe",
        "npm",
        "npm.cmd",
        "npx",
        "npx.cmd",
        "tsc",
        "tsc.cmd",
        "uv",
        "uv.exe",
        "git",
        "git.exe",
    }
)

_SAFE_ENV_VAR_NAMES: Final = frozenset(
    {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "TEMP",
        "TMP",
        "HOMEDRIVE",
        "HOMEPATH",
        "APPDATA",
        "LOCALAPPDATA",
        "COMSPEC",
        "USERPROFILE",
        "PYTHONPATH",
        "NODE_PATH",
    }
)


def _safe_environment(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Construct sanitized environment containing only essential system path variables."""
    env = {name: value for name, value in os.environ.items() if name.upper() in _SAFE_ENV_VAR_NAMES}
    if overrides:
        for k, v in overrides.items():
            if _is_safe_env_key(k):
                env[k] = v
    return env


def _is_safe_env_key(key: str) -> bool:
    """Ensure custom env override doesn't inject API keys or secrets."""
    k_upper = key.upper()
    forbidden_tokens = ("KEY", "SECRET", "TOKEN", "PASSWORD", "AUTH", "CREDENTIAL", "BEARER")
    return not any(tok in k_upper for tok in forbidden_tokens)


def _bound_text(text: str) -> str:
    """Cap output text to prevent unbounded memory or database bloat."""
    if len(text) > MAX_OUTPUT_CHARACTERS:
        return text[:MAX_OUTPUT_CHARACTERS] + "\n... (output truncated)"
    return text


def validate_workspace_path(path_to_check: str | Path, workspace_root: str | Path) -> Path:
    """Validate that path_to_check is safely contained within workspace_root."""
    try:
        ws_resolved = Path(workspace_root).resolve()
        target_resolved = Path(path_to_check).resolve()
    except Exception as exc:
        raise QualitySecurityError(f"Invalid path resolution: {exc}") from exc

    if not ws_resolved.is_dir():
        raise QualitySecurityError(
            f"Workspace root does not exist or is not a directory: {ws_resolved}"
        )

    try:
        target_resolved.relative_to(ws_resolved)
    except ValueError as exc:
        raise QualitySecurityError(
            f"Path escape violation: path '{target_resolved}' is outside "
            f"approved workspace '{ws_resolved}'"
        ) from exc

    return target_resolved


@dataclass(frozen=True)
class SafeProcessExecutionResult:
    """Result of running an approved quality verification process."""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    duration_ms: float = 0.0


class SafeQualityProcessRunner:
    """Defensive runner executing verification commands within workspace isolation."""

    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        if not self.workspace_root.is_dir():
            raise QualitySecurityError(
                f"Workspace root '{self.workspace_root}' is not an existing directory"
            )

    def run(
        self,
        argv: list[str] | tuple[str, ...],
        cwd: str | Path | None = None,
        timeout_seconds: float = 30.0,
        env_overrides: dict[str, str] | None = None,
    ) -> SafeProcessExecutionResult:
        """Run an allow-listed executable with defensive isolation."""
        if not argv:
            raise QualitySecurityError("argv must not be empty")

        raw_exec = argv[0]
        # Resolve executable basename
        exec_name = Path(raw_exec).name.lower()
        if (
            exec_name not in ALLOWED_QUALITY_EXECUTABLES
            and raw_exec.lower() not in ALLOWED_QUALITY_EXECUTABLES
        ):
            raise UnapprovedQualityCommandError(
                f"Executable '{raw_exec}' is not permitted in Quality Factory allowlist."
            )

        # Validate working directory
        work_dir = validate_workspace_path(cwd or self.workspace_root, self.workspace_root)

        # Enforce bounded timeout
        timeout = min(max(1.0, float(timeout_seconds)), 600.0)

        import time

        start_time = time.perf_counter()

        try:
            completed = subprocess.run(  # noqa: S603 - shell=False, argv-only, allow-listed executable
                list(argv),
                cwd=str(work_dir),
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=_safe_environment(env_overrides),
            )
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return SafeProcessExecutionResult(
                exit_code=completed.returncode,
                stdout=_bound_text(completed.stdout or ""),
                stderr=_bound_text(completed.stderr or ""),
                timed_out=False,
                duration_ms=duration_ms,
            )
        except subprocess.TimeoutExpired as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            stdout_str = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr_str = exc.stderr if isinstance(exc.stderr, str) else ""
            return SafeProcessExecutionResult(
                exit_code=-1,
                stdout=_bound_text(stdout_str),
                stderr=_bound_text(f"{stderr_str}\nProcess timed out after {timeout} seconds."),
                timed_out=True,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return SafeProcessExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=_bound_text(f"Process execution error: {exc}"),
                timed_out=False,
                duration_ms=duration_ms,
            )


__all__ = [
    "ALLOWED_QUALITY_EXECUTABLES",
    "MAX_OUTPUT_CHARACTERS",
    "SafeProcessExecutionResult",
    "SafeQualityProcessRunner",
    "validate_workspace_path",
]
