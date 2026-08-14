"""Tests for the Google Antigravity adapter's real `agy -p` contract."""

import pytest

from app.adapters.antigravity import AntigravityAdapter
from app.adapters.exceptions import AgentOutputError
from app.adapters.process_runner import ProcessResult
from app.adapters.prompt_builder import PromptBuilder
from app.adapters.types import CLIProfile, create_cli_profile
from app.engine.executor import StepExecutionRequest
from tests.support.fakes import FakeProcessRunner


def _profile() -> CLIProfile:
    return create_cli_profile(
        agent_type="antigravity",
        enabled=True,
        executable="agy",
        arguments=["-p", "{prompt}"],
        input_mode="prompt_argument",
        output_mode="text",
        timeout_seconds=300.0,
        max_output_characters=50000,
    )


def _request() -> StepExecutionRequest:
    return StepExecutionRequest(
        workflow_id="wf-1",
        step_id="step-1",
        step_name="antigravity-step",
        agent_type="antigravity",
        step_input={},
        workflow_input={},
        previous_step_outputs={},
    )


def test_parses_plain_text_result() -> None:
    runner = FakeProcessRunner(
        result=ProcessResult(exit_code=0, stdout="  final response\n", stderr="")
    )
    adapter = AntigravityAdapter(_profile(), runner, PromptBuilder(max_prompt_characters=10000))

    result = adapter.execute(_request())

    assert result["content"] == "final response"
    assert result["agent_type"] == "antigravity"
    assert result["metadata"]["execution_mode"] == "local_cli"


def test_invokes_agy_with_p_and_one_prompt_argument() -> None:
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout="done", stderr=""))
    adapter = AntigravityAdapter(_profile(), runner, PromptBuilder(max_prompt_characters=10000))

    adapter.execute(_request())

    executable, arguments = runner.calls[0]
    assert executable == "agy"
    assert arguments[0] == "-p"
    assert len(arguments) == 2
    assert "wf-1" in arguments[1]


def test_empty_text_output_raises_agent_output_error() -> None:
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout="   ", stderr=""))
    adapter = AntigravityAdapter(_profile(), runner, PromptBuilder(max_prompt_characters=10000))

    with pytest.raises(AgentOutputError):
        adapter.execute(_request())


def test_never_labeled_as_gemini() -> None:
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout="ok", stderr=""))
    adapter = AntigravityAdapter(_profile(), runner, PromptBuilder(max_prompt_characters=10000))

    result = adapter.execute(_request())

    assert result["agent_type"] == "antigravity"
    assert result["agent_type"] != "gemini"
