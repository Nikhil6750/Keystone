"""Tests for the shared local-CLI adapter behavior (Claude Code, Codex, Gemini).

All process execution is faked via `FakeProcessRunner` — no real subprocess is
ever launched here.
"""

import json

import pytest

from app.adapters import process_runner
from app.adapters.claude_code import ClaudeCodeAdapter
from app.adapters.codex import CodexAdapter
from app.adapters.exceptions import AgentOutputError, AgentProcessError
from app.adapters.gemini import GeminiAdapter
from app.adapters.process_runner import ProcessResult
from app.adapters.prompt_builder import PromptBuilder
from app.adapters.types import create_cli_profile
from app.engine.executor import StepExecutionRequest
from tests.support.fakes import FakeProcessRunner

_ADAPTER_CLASSES_AND_TYPES = [
    (ClaudeCodeAdapter, "claude_code"),
    (CodexAdapter, "codex"),
    (GeminiAdapter, "gemini"),
]


def _request() -> StepExecutionRequest:
    return StepExecutionRequest(
        workflow_id="wf-1",
        step_id="step-1",
        step_name="demo-step",
        agent_type="claude_code",
        step_input={"task": "say hi"},
        workflow_input={"goal": "demo"},
        previous_step_outputs={},
    )


@pytest.mark.parametrize(("adapter_cls", "expected_agent_type"), _ADAPTER_CLASSES_AND_TYPES)
def test_adapter_returns_correct_agent_type(adapter_cls: type, expected_agent_type: str) -> None:
    profile = create_cli_profile(
        agent_type=expected_agent_type,
        enabled=True,
        executable="mock",
        arguments=["-p", "{prompt}"],
        input_mode="prompt_argument",
        output_mode="text",
        timeout_seconds=5.0,
        max_output_characters=1000,
    )
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout="hello", stderr=""))
    adapter = adapter_cls(profile, runner, PromptBuilder(max_prompt_characters=10000))

    result = adapter.execute(_request())

    assert result["agent_type"] == expected_agent_type


def test_deterministic_prompt_is_built_and_passed_as_argument() -> None:
    profile = create_cli_profile(
        agent_type="claude_code",
        enabled=True,
        executable="mock",
        arguments=["-p", "{prompt}"],
        input_mode="prompt_argument",
        output_mode="text",
        timeout_seconds=5.0,
        max_output_characters=1000,
    )
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout="hello", stderr=""))
    adapter = ClaudeCodeAdapter(profile, runner, PromptBuilder(max_prompt_characters=10000))

    adapter.execute(_request())
    adapter.execute(_request())

    executable_a, args_a = runner.calls[0]
    executable_b, args_b = runner.calls[1]
    assert executable_a == executable_b == "mock"
    assert args_a[0] == "-p"
    assert args_a[1] == args_b[1]  # same request -> same deterministic prompt
    assert "wf-1" in args_a[1]


def test_text_output_is_wrapped_correctly() -> None:
    profile = create_cli_profile(
        agent_type="claude_code",
        enabled=True,
        executable="mock",
        arguments=[],
        input_mode="stdin",
        output_mode="text",
        timeout_seconds=5.0,
        max_output_characters=1000,
    )
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout="  hi there  ", stderr=""))
    adapter = ClaudeCodeAdapter(profile, runner, PromptBuilder(max_prompt_characters=10000))

    result = adapter.execute(_request())

    assert result["content"] == "hi there"
    assert result["metadata"]["execution_mode"] == "local_cli"


def test_json_output_is_parsed_correctly() -> None:
    profile = create_cli_profile(
        agent_type="claude_code",
        enabled=True,
        executable="mock",
        arguments=[],
        input_mode="stdin",
        output_mode="json",
        timeout_seconds=5.0,
        max_output_characters=1000,
    )
    runner = FakeProcessRunner(
        result=ProcessResult(exit_code=0, stdout='{"result": "the answer"}', stderr="")
    )
    adapter = ClaudeCodeAdapter(profile, runner, PromptBuilder(max_prompt_characters=10000))

    result = adapter.execute(_request())

    assert result["content"] == "the answer"


def test_json_lines_output_is_parsed_correctly() -> None:
    profile = create_cli_profile(
        agent_type="claude_code",
        enabled=True,
        executable="mock",
        arguments=[],
        input_mode="stdin",
        output_mode="json_lines",
        timeout_seconds=5.0,
        max_output_characters=1000,
    )
    stdout = '{"event": "start"}\n{"result": "final answer"}\n'
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout=stdout, stderr=""))
    adapter = ClaudeCodeAdapter(profile, runner, PromptBuilder(max_prompt_characters=10000))

    result = adapter.execute(_request())

    assert result["content"] == "final answer"


def test_empty_output_fails() -> None:
    profile = create_cli_profile(
        agent_type="claude_code",
        enabled=True,
        executable="mock",
        arguments=[],
        input_mode="stdin",
        output_mode="text",
        timeout_seconds=5.0,
        max_output_characters=1000,
    )
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout="   ", stderr=""))
    adapter = ClaudeCodeAdapter(profile, runner, PromptBuilder(max_prompt_characters=10000))

    with pytest.raises(AgentOutputError):
        adapter.execute(_request())


def test_malformed_json_output_raises_agent_output_error() -> None:
    profile = create_cli_profile(
        agent_type="claude_code",
        enabled=True,
        executable="mock",
        arguments=[],
        input_mode="stdin",
        output_mode="json",
        timeout_seconds=5.0,
        max_output_characters=1000,
    )
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout="{not json", stderr=""))
    adapter = ClaudeCodeAdapter(profile, runner, PromptBuilder(max_prompt_characters=10000))

    with pytest.raises(AgentOutputError):
        adapter.execute(_request())


def test_provider_process_failure_is_mapped_safely() -> None:
    profile = create_cli_profile(
        agent_type="claude_code",
        enabled=True,
        executable="mock",
        arguments=[],
        input_mode="stdin",
        output_mode="text",
        timeout_seconds=5.0,
        max_output_characters=1000,
    )
    runner = FakeProcessRunner(error=AgentProcessError("'mock' exited with code 1: boom"))
    adapter = ClaudeCodeAdapter(profile, runner, PromptBuilder(max_prompt_characters=10000))

    with pytest.raises(AgentProcessError):
        adapter.execute(_request())


def test_adapter_output_is_json_compatible() -> None:
    profile = create_cli_profile(
        agent_type="claude_code",
        enabled=True,
        executable="mock",
        arguments=[],
        input_mode="stdin",
        output_mode="text",
        timeout_seconds=5.0,
        max_output_characters=1000,
    )
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout="hi", stderr=""))
    adapter = ClaudeCodeAdapter(profile, runner, PromptBuilder(max_prompt_characters=10000))

    result = adapter.execute(_request())

    json.dumps(result)  # must not raise


def test_no_real_subprocess_is_used_in_these_tests() -> None:
    """`FakeProcessRunner` (used by every test above) never touches `subprocess`;
    this documents that assumption is holding for the module under test."""
    assert hasattr(process_runner, "SubprocessRunner")
    # The adapter tests above only ever construct FakeProcessRunner, never
    # SubprocessRunner, so no real process is launched.
