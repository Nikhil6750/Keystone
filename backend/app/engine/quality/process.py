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

import contextlib
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

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

_APPROVED_PYTHON_MODULES: Final = frozenset(
    {"pytest", "unittest", "ruff", "mypy", "compileall"}
)

_APPROVED_NPX_PACKAGES: Final = frozenset(
    {"eslint", "tsc", "prettier", "typescript"}
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


def resolve_and_validate_target_path(
    workspace_root: str | Path,
    target_path: str | Path | None,
    default: str = ".",
) -> tuple[Path, str]:
    """Resolve and validate a target_path parameter against workspace boundaries.

    Returns (resolved_absolute_path, safe_relative_path_string).
    Raises QualitySecurityError on directory traversal (..), path escape,
    outside absolute path, or symlink escape.
    """
    if target_path is not None and not isinstance(target_path, (str, Path)):
        raise QualitySecurityError(
            "Invalid target_path: expected a string or filesystem path."
        )

    raw_target = str(target_path).strip() if target_path is not None else default
    if not raw_target:
        raw_target = default
    if "\x00" in raw_target:
        raise QualitySecurityError("Invalid target_path: NUL characters are not permitted.")

    ws_root = Path(workspace_root).resolve()
    if not ws_root.is_dir():
        raise QualitySecurityError(
            f"Workspace root does not exist or is not a directory: {ws_root}"
        )

    candidate = Path(raw_target)
    if candidate.is_absolute():
        resolved = validate_workspace_path(candidate, ws_root)
    else:
        resolved = validate_workspace_path(ws_root / candidate, ws_root)

    try:
        rel_str = str(resolved.relative_to(ws_root))
        if rel_str in ("", "."):
            rel_str = "."
    except ValueError as exc:
        raise QualitySecurityError(
            f"Path escape violation: path '{resolved}' is outside workspace '{ws_root}'"
        ) from exc

    return resolved, rel_str


def _validate_safe_command_arguments(argv: list[str]) -> None:
    """Reject dangerous interpreter flags, arbitrary code injection, and unsafe commands."""
    if not argv:
        raise QualitySecurityError("argv must not be empty")

    raw_exec = argv[0]
    exec_name = Path(raw_exec).name.lower()
    if (
        exec_name not in ALLOWED_QUALITY_EXECUTABLES
        and raw_exec.lower() not in ALLOWED_QUALITY_EXECUTABLES
    ):
        raise UnapprovedQualityCommandError(
            f"Executable '{raw_exec}' is not permitted in Quality Factory allowlist."
        )

    # 1. Python safety checks: forbid -c / --command
    if exec_name in ("python", "python.exe"):
        for i, arg in enumerate(argv[1:], start=1):
            if arg in ("-c", "--command"):
                raise QualitySecurityError(
                    "Executing arbitrary Python code strings via -c is strictly forbidden."
                )
            if arg == "-m" and i + 1 < len(argv):
                mod_name = argv[i + 1].lower()
                if mod_name not in _APPROVED_PYTHON_MODULES:
                    raise QualitySecurityError(
                        f"Python module '{mod_name}' is not in approved verification modules: "
                        f"{sorted(_APPROVED_PYTHON_MODULES)}"
                    )

    # 2. Node safety checks: forbid -e / --eval / -p / --print
    elif exec_name in ("node", "node.exe"):
        for arg in argv[1:]:
            if arg in ("-e", "--eval", "-p", "--print"):
                raise QualitySecurityError(
                    "Executing arbitrary Node.js code strings via eval flags is strictly forbidden."
                )

    # 3. NPX safety checks: forbid arbitrary package execution
    elif exec_name in ("npx", "npx.cmd") and len(argv) > 1:
        pkg_name = argv[1].lower()
        if pkg_name not in _APPROVED_NPX_PACKAGES:
            raise QualitySecurityError(
                f"npx package '{pkg_name}' is not in approved verification tools: "
                f"{sorted(_APPROVED_NPX_PACKAGES)}"
            )


def _terminate_process_tree(proc: subprocess.Popen[str]) -> None:
    """Terminate the process and its entire descendant process tree cleanly."""
    try:
        if sys.platform == "win32":
            # On Windows: use taskkill /F /T to recursively kill the process tree
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    check=False,
                    timeout=5.0,
                )
            except Exception:
                proc.kill()
        else:
            # On POSIX: kill the process group
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                proc.kill()
    except Exception:
        with contextlib.suppress(Exception):
            proc.kill()


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
        """Run an allow-listed executable with defensive isolation and tree termination."""
        arg_list = list(argv)
        _validate_safe_command_arguments(arg_list)

        # Validate working directory
        work_dir = validate_workspace_path(cwd or self.workspace_root, self.workspace_root)

        # Enforce bounded timeout
        timeout = min(max(1.0, float(timeout_seconds)), 600.0)

        start_time = time.perf_counter()

        popen_kwargs: dict[str, Any] = {
            "cwd": str(work_dir),
            "shell": False,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "env": _safe_environment(env_overrides),
        }

        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        proc: subprocess.Popen[str] | None = None
        try:
            proc = subprocess.Popen(  # noqa: S603 - shell=False, argv-only, allowlisted
                arg_list,
                **popen_kwargs,
            )
            stdout, stderr = proc.communicate(timeout=timeout)
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return SafeProcessExecutionResult(
                exit_code=proc.returncode,
                stdout=_bound_text(stdout or ""),
                stderr=_bound_text(stderr or ""),
                timed_out=False,
                duration_ms=duration_ms,
            )
        except subprocess.TimeoutExpired:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            if proc is not None:
                _terminate_process_tree(proc)
                try:
                    stdout, stderr = proc.communicate(timeout=2.0)
                except Exception:
                    stdout, stderr = "", ""
            else:
                stdout, stderr = "", ""

            return SafeProcessExecutionResult(
                exit_code=-1,
                stdout=_bound_text(stdout or ""),
                stderr=_bound_text(f"{stderr}\nProcess timed out after {timeout} seconds."),
                timed_out=True,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            if proc is not None:
                _terminate_process_tree(proc)
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
    "resolve_and_validate_target_path",
    "validate_workspace_path",
]
