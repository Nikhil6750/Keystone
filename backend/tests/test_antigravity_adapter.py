"""Tests for the Google Antigravity adapter's JSON parsing and error
classification.

The sanitized JSON fixtures below match the result envelope live-verified
against `agy.exe` 1.1.10.
"""

import json

import pytest

from app.adapters.antigravity import AntigravityAdapter
from app.adapters.exceptions import AgentAuthenticationError, AgentOutputError
from app.adapters.process_runner import ProcessResult
from app.adapters.prompt_builder import PromptBuilder
from app.adapters.types import create_cli_profile
from app.engine.executor import StepExecutionRequest
from tests.support.fakes import FakeProcessRunner


def _profile() -> object:
    return create_cli_profile(
        agent_type="antigravity",
        enabled=True,
        executable="agy",
        arguments=["-p", "--output-format", "json", "{prompt}"],
        input_mode="prompt_argument",
        output_mode="json",
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


def test_parses_json_result_field() -> None:
    runner = FakeProcessRunner(
        result=ProcessResult(
            exit_code=0,
            stdout=json.dumps({"result": "final response", "session_id": "s-1", "model": "m-1"}),
            stderr="",
        )
    )
    adapter = AntigravityAdapter(_profile(), runner, PromptBuilder(max_prompt_characters=10000))  # type: ignore[arg-type]

    result = adapter.execute(_request())

    assert result["content"] == "final response"
    assert result["agent_type"] == "antigravity"
    assert result["metadata"]["provider_session_id"] == "s-1"
    assert result["metadata"]["model"] == "m-1"


def test_authentication_required_error_is_classified() -> None:
    runner = FakeProcessRunner(
        result=ProcessResult(
            exit_code=0,
            stdout=json.dumps(
                {"is_error": True, "error": "Please sign in to continue using Antigravity."}
            ),
            stderr="",
        )
    )
    adapter = AntigravityAdapter(_profile(), runner, PromptBuilder(max_prompt_characters=10000))  # type: ignore[arg-type]

    with pytest.raises(AgentAuthenticationError):
        adapter.execute(_request())


def test_malformed_output_raises_agent_output_error() -> None:
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout="not json", stderr=""))
    adapter = AntigravityAdapter(_profile(), runner, PromptBuilder(max_prompt_characters=10000))  # type: ignore[arg-type]

    with pytest.raises(AgentOutputError):
        adapter.execute(_request())


def test_non_object_json_raises_agent_output_error() -> None:
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout="[1, 2, 3]", stderr=""))
    adapter = AntigravityAdapter(_profile(), runner, PromptBuilder(max_prompt_characters=10000))  # type: ignore[arg-type]

    with pytest.raises(AgentOutputError):
        adapter.execute(_request())


def test_no_recognizable_content_key_raises_agent_output_error() -> None:
    runner = FakeProcessRunner(
        result=ProcessResult(exit_code=0, stdout=json.dumps({"unexpected": "shape"}), stderr="")
    )
    adapter = AntigravityAdapter(_profile(), runner, PromptBuilder(max_prompt_characters=10000))  # type: ignore[arg-type]

    with pytest.raises(AgentOutputError):
        adapter.execute(_request())


def test_never_labeled_as_gemini() -> None:
    """Antigravity's own agent_type must never be reported as 'gemini'."""
    runner = FakeProcessRunner(
        result=ProcessResult(exit_code=0, stdout=json.dumps({"result": "ok"}), stderr="")
    )
    adapter = AntigravityAdapter(_profile(), runner, PromptBuilder(max_prompt_characters=10000))  # type: ignore[arg-type]

    result = adapter.execute(_request())

    assert result["agent_type"] == "antigravity"
    assert result["agent_type"] != "gemini"
