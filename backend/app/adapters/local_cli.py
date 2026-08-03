"""Shared local-CLI `AgentExecutor` implementation.

Provider adapters (Claude Code, Codex, Gemini) subclass this directly; prompt
construction, process execution, and output parsing are all shared here so
provider-specific code stays minimal.
"""

import json
from typing import Any

from app.adapters.base import build_agent_result
from app.adapters.exceptions import AgentOutputError
from app.adapters.process_runner import ProcessRunner
from app.adapters.prompt_builder import PromptBuilder
from app.adapters.types import PROMPT_PLACEHOLDER, CLIProfile, InputMode, OutputMode
from app.engine.executor import StepExecutionRequest

_CONTENT_KEYS = ("result", "content", "text", "output", "response")


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

        if self._profile.input_mode is InputMode.PROMPT_ARGUMENT:
            arguments = [
                prompt if arg == PROMPT_PLACEHOLDER else arg for arg in self._profile.arguments
            ]
            stdin_text = None
        else:
            arguments = list(self._profile.arguments)
            stdin_text = prompt

        result = self._process_runner.run(
            self._profile.executable,
            arguments,
            stdin_text=stdin_text,
            timeout_seconds=self._profile.timeout_seconds,
            max_output_characters=self._profile.max_output_characters,
        )

        content = _parse_output(result.stdout, self._profile.output_mode)
        return build_agent_result(
            agent_type=self._profile.agent_type,
            content=content,
            execution_mode="local_cli",
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
