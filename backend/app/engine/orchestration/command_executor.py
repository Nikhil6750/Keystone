"""The first real implementation of Stage 4E's `CommandExecutor` seam
(`app.engine.verification.evaluators.CommandExecutor`/`CommandSpec`), which
until now was deliberately documented-but-unused infrastructure (the
default `NullCommandExecutor` always refuses).

`SubprocessCommandExecutor` is deliberately narrow and defensive, matching
every safety constraint verification-evidence collection must uphold:

- `shell=False`, argv-only -- never a shell string, never subject to shell
  metacharacter/quoting issues.
- An approved-executable allow-list (`ALLOWED_EXECUTABLES`) -- the only
  executables Keystone's evidence collector may ever invoke. `argv` itself
  is always constructed by `evidence_collector.py`'s fixed policy, never
  taken from a prompt, model response, ConnectedAgent metadata, webview, or
  README.
- A bounded timeout (`CommandSpec.timeout_seconds`, always caller-supplied
  and positive -- enforced by `CommandSpec.__post_init__`).
- Bounded captured output (`MAX_OUTPUT_CHARACTERS`) -- a pathological
  command can never buffer or return unbounded text.
- A minimal environment (`_safe_environment`) -- only what's needed to
  resolve and run `node`/`python` from `PATH`; no credential, token, or
  secret environment variable the host process might hold is ever passed
  through to a spawned verification command.
- `cwd` is always the caller's already-validated `workspace_root`
  (`app.adapters.workspace.validate_workspace_root`) -- this class performs
  no path validation of its own beyond requiring `cwd` to already exist.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Final

from app.engine.verification.evaluators import CommandExecutionOutcome, CommandSpec

MAX_OUTPUT_CHARACTERS: Final = 20_000

ALLOWED_EXECUTABLES: Final = frozenset({"node", "python"})

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
    }
)


class UnapprovedCommandError(ValueError):
    """Raised when asked to run an executable outside `ALLOWED_EXECUTABLES`."""


def _safe_environment() -> dict[str, str]:
    return {
        name: value for name, value in os.environ.items() if name.upper() in _SAFE_ENV_VAR_NAMES
    }


def _bounded(text: str) -> str:
    if len(text) > MAX_OUTPUT_CHARACTERS:
        return text[:MAX_OUTPUT_CHARACTERS] + "\n... (output truncated)"
    return text


class SubprocessCommandExecutor:
    """A real, policy-constrained `CommandExecutor`. See module docstring
    for the full list of safety constraints this class enforces."""

    def run(self, spec: CommandSpec) -> CommandExecutionOutcome:
        executable = spec.argv[0]
        if executable not in ALLOWED_EXECUTABLES:
            raise UnapprovedCommandError(
                f"executable {executable!r} is not in the approved evidence-collection allow-list"
            )
        if spec.cwd is None or not Path(spec.cwd).is_dir():
            raise ValueError("CommandSpec.cwd must be an existing directory")

        try:
            completed = subprocess.run(  # noqa: S603 - shell=False, argv-only, allow-listed executable
                list(spec.argv),
                cwd=spec.cwd,
                shell=False,
                capture_output=True,
                text=True,
                timeout=spec.timeout_seconds,
                env=_safe_environment(),
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            return CommandExecutionOutcome(
                exit_code=-1, stdout=_bounded(stdout), stderr=_bounded(stderr), timed_out=True
            )
        except OSError as exc:
            return CommandExecutionOutcome(exit_code=127, stdout="", stderr=_bounded(str(exc)))

        return CommandExecutionOutcome(
            exit_code=completed.returncode,
            stdout=_bounded(completed.stdout or ""),
            stderr=_bounded(completed.stderr or ""),
        )


__all__ = ["ALLOWED_EXECUTABLES", "SubprocessCommandExecutor", "UnapprovedCommandError"]
