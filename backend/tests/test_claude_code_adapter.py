"""Tests for the Claude Code adapter's real JSON parsing and error
classification, modeled on the exact envelope shape observed from a live
`claude -p ... --output-format json` call (see `docs/live-agent-connectors.md`).
All process execution is faked — no real subprocess is ever launched here.
"""

import json

import pytest

from app.adapters.claude_code import ClaudeCodeAdapter
from app.adapters.connection import AuthenticationStatus
from app.adapters.exceptions import (
    AgentAuthenticationError,
    AgentOutputError,
    AgentUsageLimitError,
)
from app.adapters.process_runner import ProcessResult
from app.adapters.prompt_builder import PromptBuilder
from app.adapters.types import create_cli_profile
from app.engine.executor import StepExecutionRequest
from tests.support.fakes import FakeProcessRunner


def _profile() -> object:
    return create_cli_profile(
        agent_type="claude_code",
        enabled=True,
        executable="claude",
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
        step_name="claude-step",
        agent_type="claude_code",
        step_input={},
        workflow_input={},
        previous_step_outputs={},
    )


def _success_envelope(result_text: str) -> str:
    return json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": result_text,
            "session_id": "session-abc",
            "duration_ms": 1234,
        }
    )


def test_parses_the_real_claude_json_envelope() -> None:
    runner = FakeProcessRunner(
        result=ProcessResult(exit_code=0, stdout=_success_envelope("hello there"), stderr="")
    )
    adapter = ClaudeCodeAdapter(_profile(), runner, PromptBuilder(max_prompt_characters=10000))  # type: ignore[arg-type]

    result = adapter.execute(_request())

    assert result["content"] == "hello there"
    assert result["metadata"]["provider_session_id"] == "session-abc"
    assert result["metadata"]["duration_ms"] == 1234


def test_authentication_failure_is_classified_and_not_retryable() -> None:
    envelope = json.dumps(
        {
            "type": "result",
            "subtype": "error_during_execution",
            "is_error": True,
            "result": "Please run `claude auth login` to authenticate.",
        }
    )
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout=envelope, stderr=""))
    adapter = ClaudeCodeAdapter(_profile(), runner, PromptBuilder(max_prompt_characters=10000))  # type: ignore[arg-type]

    with pytest.raises(AgentAuthenticationError) as excinfo:
        adapter.execute(_request())
    assert excinfo.value.retryable is False


def test_usage_limit_failure_is_classified() -> None:
    envelope = json.dumps(
        {
            "type": "result",
            "subtype": "error_during_execution",
            "is_error": True,
            "result": "You have hit your usage limit for this billing period.",
        }
    )
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout=envelope, stderr=""))
    adapter = ClaudeCodeAdapter(_profile(), runner, PromptBuilder(max_prompt_characters=10000))  # type: ignore[arg-type]

    with pytest.raises(AgentUsageLimitError):
        adapter.execute(_request())


def test_malformed_json_raises_agent_output_error() -> None:
    runner = FakeProcessRunner(
        result=ProcessResult(exit_code=0, stdout="not json at all", stderr="")
    )
    adapter = ClaudeCodeAdapter(_profile(), runner, PromptBuilder(max_prompt_characters=10000))  # type: ignore[arg-type]

    with pytest.raises(AgentOutputError):
        adapter.execute(_request())


def test_missing_result_text_raises_agent_output_error() -> None:
    envelope = json.dumps({"type": "result", "subtype": "success", "is_error": False})
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout=envelope, stderr=""))
    adapter = ClaudeCodeAdapter(_profile(), runner, PromptBuilder(max_prompt_characters=10000))  # type: ignore[arg-type]

    with pytest.raises(AgentOutputError):
        adapter.execute(_request())


def test_check_authentication_reads_only_the_logged_in_flag() -> None:
    runner = FakeProcessRunner(
        result=ProcessResult(
            exit_code=0,
            stdout=json.dumps(
                {
                    "loggedIn": True,
                    "email": "someone@example.com",
                    "orgId": "org-123",
                }
            ),
            stderr="",
        )
    )
    adapter = ClaudeCodeAdapter(_profile(), runner, PromptBuilder(max_prompt_characters=10000))  # type: ignore[arg-type]

    status = adapter.check_authentication()

    assert status is AuthenticationStatus.AUTHENTICATED


def test_check_authentication_reports_unauthenticated() -> None:
    runner = FakeProcessRunner(
        result=ProcessResult(exit_code=0, stdout=json.dumps({"loggedIn": False}), stderr="")
    )
    adapter = ClaudeCodeAdapter(_profile(), runner, PromptBuilder(max_prompt_characters=10000))  # type: ignore[arg-type]

    assert adapter.check_authentication() is AuthenticationStatus.UNAUTHENTICATED


def test_check_authentication_reports_unknown_on_unparseable_output() -> None:
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout="not json", stderr=""))
    adapter = ClaudeCodeAdapter(_profile(), runner, PromptBuilder(max_prompt_characters=10000))  # type: ignore[arg-type]

    assert adapter.check_authentication() is AuthenticationStatus.UNKNOWN
