"""Shared local-CLI `AgentExecutor` implementation.

Provider adapters (Claude Code, Codex, Google Antigravity, Gemini) subclass
this; prompt construction and process invocation are always shared here.
Output parsing and error classification are generic by default (used as-is
by the still-unconfigured `GeminiAdapter`) but a subclass may override
`_build_result` for provider-specific JSON/JSONL parsing and error
classification (see `claude_code.py`, `codex.py`, `antigravity.py`).
"""

import json
import shutil
from typing import Any

from app.adapters.base import build_agent_result
from app.adapters.connection import (
    AuthenticationStatus,
    ConnectionStatus,
    InstallationStatus,
    build_verification_prompt,
    new_verification_token,
)
from app.adapters.exceptions import AgentAdapterError, AgentOutputError
from app.adapters.process_runner import ProcessResult, ProcessRunner
from app.adapters.prompt_builder import PromptBuilder
from app.adapters.types import PROMPT_PLACEHOLDER, CLIProfile, InputMode, OutputMode
from app.engine.executor import StepExecutionRequest

_CONTENT_KEYS = ("result", "content", "text", "output", "response")
_VERSION_TIMEOUT_SECONDS = 10.0
_VERSION_MAX_OUTPUT_CHARACTERS = 2000


class LocalCLIAdapter:
    """Runs one local CLI per its `CLIProfile`, returning a JSON-compatible result."""

    def __init__(
        self,
        profile: CLIProfile,
        process_runner: ProcessRunner,
        prompt_builder: PromptBuilder,
    ) -> None:
        self._profile = profile
        self._process_runner = process_runner
        self._prompt_builder = prompt_builder

    def execute(self, request: StepExecutionRequest) -> dict[str, Any]:
        prompt = self._prompt_builder.build(request)
        result = self._run_process(prompt)
        return self._build_result(result)

    def _run_process(self, prompt: str) -> ProcessResult:
        """Build the argument list/stdin from the profile and invoke the
        shared, secure `ProcessRunner` — identical for every provider."""
        if self._profile.input_mode is InputMode.PROMPT_ARGUMENT:
            arguments = [
                prompt if arg == PROMPT_PLACEHOLDER else arg for arg in self._profile.arguments
            ]
            stdin_text = None
        else:
            arguments = list(self._profile.arguments)
            stdin_text = prompt

        return self._process_runner.run(
            self._profile.executable,
            arguments,
            stdin_text=stdin_text,
            timeout_seconds=self._profile.timeout_seconds,
            max_output_characters=self._profile.max_output_characters,
        )

    def _build_result(self, result: ProcessResult) -> dict[str, Any]:
        """Generic parsing: extract a plain text/JSON/JSON-lines result with
        no provider-specific error classification. Overridden by
        provider-specific adapters that know their own CLI's actual schema."""
        content = _parse_output(result.stdout, self._profile.output_mode)
        return build_agent_result(
            agent_type=self._profile.agent_type,
            content=content,
            execution_mode="local_cli",
        )

    # --- Connection verification (shared by every local CLI adapter) ---

    def detect(self) -> InstallationStatus:
        """Whether the configured executable currently resolves on `PATH`."""
        return (
            InstallationStatus.INSTALLED
            if shutil.which(self._profile.executable) is not None
            else InstallationStatus.NOT_INSTALLED
        )

    def read_version(self) -> str | None:
        """Run `<executable> --version` and return its first output line.

        Never raises — a failure here (missing executable, unexpected flag,
        timeout) simply means the version could not be safely determined.
        """
        try:
            result = self._process_runner.run(
                self._profile.executable,
                ["--version"],
                stdin_text=None,
                timeout_seconds=_VERSION_TIMEOUT_SECONDS,
                max_output_characters=_VERSION_MAX_OUTPUT_CHARACTERS,
            )
        except AgentAdapterError:
            return None
        text = (result.stdout or result.stderr).strip()
        return text.splitlines()[0].strip() if text else None

    def check_authentication(self) -> AuthenticationStatus:
        """Default: no generic, safe authentication-status command is known
        for every provider. Providers with one (Claude Code, Codex) override
        this; providers without one (Google Antigravity, the still-reserved
        Gemini slot) fall back to deriving authentication only from whether
        `verify_connection` itself succeeds."""
        return AuthenticationStatus.UNKNOWN

    def verify_connection(self) -> tuple[ConnectionStatus, str]:
        """Run one harmless headless prompt with a fresh, unpredictable token
        and confirm the parsed response contains exactly that token."""
        token = new_verification_token(self._profile.agent_type)
        prompt = build_verification_prompt(token)
        try:
            result = self._run_process(prompt)
            parsed = self._build_result(result)
        except AgentAdapterError as exc:
            return ConnectionStatus.VERIFICATION_FAILED, str(exc)
        content = str(parsed.get("content", ""))
        if token in content:
            return ConnectionStatus.CONNECTED, "Verified via a harmless headless prompt"
        return (
            ConnectionStatus.VERIFICATION_FAILED,
            "The response did not contain the expected verification token",
        )


def _parse_output(stdout: str, output_mode: OutputMode) -> str:
    if output_mode is OutputMode.TEXT:
        content = stdout.strip()
        if not content:
            raise AgentOutputError("agent produced empty text output")
        return content

    if output_mode is OutputMode.JSON:
        return _extract_content(_parse_json_object(stdout.strip()))

    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise AgentOutputError("agent produced no JSON-lines output")
    return _extract_content(_parse_json_object(lines[-1]))


def _parse_json_object(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise AgentOutputError("agent output was not valid JSON") from exc


def _extract_content(parsed: Any) -> str:
    if isinstance(parsed, dict):
        for key in _CONTENT_KEYS:
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return json.dumps(parsed, sort_keys=True)
    if isinstance(parsed, str) and parsed.strip():
        return parsed.strip()
    return json.dumps(parsed, sort_keys=True)
