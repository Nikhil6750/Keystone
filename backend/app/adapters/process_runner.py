"""Safe, injectable subprocess execution for local CLI agent adapters.

Never uses a shell: arguments are always passed as a list to `subprocess.run`
with `shell=False`. Only trusted, settings-derived executable names and
argument lists reach this layer — workflow payloads never do.
"""

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Protocol

from app.adapters.exceptions import (
    AgentOutputError,
    AgentProcessError,
    AgentTimeoutError,
    AgentUnavailableError,
)

logger = logging.getLogger(__name__)

_STDERR_LIMIT = 300
_INHERITED_ENV_KEYS = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE")


@dataclass(frozen=True)
class ProcessResult:
    """The outcome of one successfully completed (exit code 0) CLI process."""

    exit_code: int
    stdout: str
    stderr: str


class ProcessRunner(Protocol):
    """Executes one CLI command. Injectable so tests never launch real processes."""

    def run(
        self,
        executable: str,
        arguments: list[str],
        *,
        stdin_text: str | None,
        timeout_seconds: float,
        max_output_characters: int,
        env_overrides: dict[str, str] | None = None,
    ) -> ProcessResult:
        """Run `executable` with `arguments`, returning its result on success.

        Raises `AgentUnavailableError` if the executable cannot be resolved,
        `AgentTimeoutError` if it exceeds `timeout_seconds`, `AgentProcessError`
        for a non-zero exit or other execution failure, and `AgentOutputError`
        if stdout exceeds `max_output_characters`.
        """
        ...


def _bound_text(text: str, limit: int) -> str:
    """Sanitize and bound diagnostic text (e.g. stderr) before logging or persisting it."""
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit] + "... [truncated]"


def _restricted_environment(overrides: dict[str, str] | None) -> dict[str, str]:
    """A minimal inherited environment plus explicit, trusted overrides.

    Never passes through the full parent environment, so unrelated credentials
    already present in it are not exposed to the child process.
    """
    restricted = {key: os.environ[key] for key in _INHERITED_ENV_KEYS if key in os.environ}
    if overrides:
        restricted.update(overrides)
    return restricted


class SubprocessRunner:
    """The real `ProcessRunner`, backed by `subprocess.run`."""

    def run(
        self,
        executable: str,
        arguments: list[str],
        *,
        stdin_text: str | None,
        timeout_seconds: float,
        max_output_characters: int,
        env_overrides: dict[str, str] | None = None,
    ) -> ProcessResult:
        resolved = shutil.which(executable)
        if resolved is None:
            raise AgentUnavailableError(f"executable '{executable}' could not be resolved on PATH")

        command = [resolved, *arguments]
        env = _restricted_environment(env_overrides)

        with tempfile.TemporaryDirectory(prefix="keystone-agent-") as work_dir:
            try:
                if stdin_text is not None:
                    completed = subprocess.run(
                        command,
                        input=stdin_text,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=timeout_seconds,
                        cwd=work_dir,
                        env=env,
                        shell=False,
                    )
                else:
                    completed = subprocess.run(
                        command,
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=timeout_seconds,
                        cwd=work_dir,
                        env=env,
                        shell=False,
                    )
            except subprocess.TimeoutExpired as exc:
                raise AgentTimeoutError(
                    f"'{executable}' did not complete within {timeout_seconds:.0f}s"
                ) from exc
            except OSError as exc:
                raise AgentProcessError(
                    f"'{executable}' failed to start: {exc.__class__.__name__}"
                ) from exc

        stdout = completed.stdout or ""
        stderr = _bound_text(completed.stderr or "", _STDERR_LIMIT)

        if len(stdout) > max_output_characters:
            raise AgentOutputError(
                f"'{executable}' produced output exceeding {max_output_characters} characters"
            )

        if completed.returncode != 0:
            logger.warning(
                "agent adapter process exited non-zero executable=%s exit_code=%s",
                executable,
                completed.returncode,
            )
            raise AgentProcessError(
                f"'{executable}' exited with code {completed.returncode}: {stderr}"
            )

        return ProcessResult(exit_code=completed.returncode, stdout=stdout, stderr=stderr)
