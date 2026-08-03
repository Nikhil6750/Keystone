"""Tests for the Codex adapter's JSONL event-stream parsing and error
classification.

IMPORTANT: `codex` was not installed in the environment this adapter was
built in — these fixtures model Codex's publicly documented `exec --json`
event-stream conventions, not a captured live response. See
`docs/live-agent-connectors.md`'s known-limitations section.
"""

import json

import pytest

from app.adapters.codex import CodexAdapter
from app.adapters.connection import AuthenticationStatus
from app.adapters.exceptions import AgentAuthenticationError, AgentOutputError
from app.adapters.process_runner import ProcessResult
from app.adapters.prompt_builder import PromptBuilder
from app.adapters.types import create_cli_profile
from app.engine.executor import StepExecutionRequest
from tests.support.fakes import FakeProcessRunner


def _profile() -> object:
    return create_cli_profile(
        agent_type="codex",
        enabled=True,
        executable="codex",
        arguments=["exec", "--json", "{prompt}"],
        input_mode="prompt_argument",
        output_mode="json_lines",
        timeout_seconds=300.0,
        max_output_characters=50000,
    )


def _request() -> StepExecutionRequest:
    return StepExecutionRequest(
        workflow_id="wf-1",
        step_id="step-1",
        step_name="codex-step",
        agent_type="codex",
        step_input={},
        workflow_input={},
        previous_step_outputs={},
    )


def _jsonl(*events: dict[str, object]) -> str:
    return "\n".join(json.dumps(event) for event in events)


def test_extracts_final_agent_message_from_jsonl_event_stream() -> None:
    stdout = _jsonl(
        {"type": "thread.started", "thread_id": "thread-1"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "final answer"}},
        {"type": "turn.completed"},
    )
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout=stdout, stderr=""))
    adapter = CodexAdapter(_profile(), runner, PromptBuilder(max_prompt_characters=10000))  # type: ignore[arg-type]

    result = adapter.execute(_request())

    assert result["content"] == "final answer"
    assert result["metadata"]["provider_session_id"] == "thread-1"


def test_ignores_progress_events_after_parsing_them() -> None:
    stdout = _jsonl(
        {"type": "turn.started"},
        {"type": "item.started", "item": {"type": "reasoning"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "done"}},
    )
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout=stdout, stderr=""))
    adapter = CodexAdapter(_profile(), runner, PromptBuilder(max_prompt_characters=10000))  # type: ignore[arg-type]

    result = adapter.execute(_request())

    assert result["content"] == "done"


def test_malformed_jsonl_line_is_skipped_not_fatal() -> None:
    stdout = "not a json line\n" + _jsonl(
        {"type": "item.completed", "item": {"type": "agent_message", "text": "recovered"}}
    )
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout=stdout, stderr=""))
    adapter = CodexAdapter(_profile(), runner, PromptBuilder(max_prompt_characters=10000))  # type: ignore[arg-type]

    result = adapter.execute(_request())

    assert result["content"] == "recovered"


def test_no_recognizable_final_message_raises_agent_output_error() -> None:
    stdout = _jsonl({"type": "turn.started"}, {"type": "turn.completed"})
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout=stdout, stderr=""))
    adapter = CodexAdapter(_profile(), runner, PromptBuilder(max_prompt_characters=10000))  # type: ignore[arg-type]

    with pytest.raises(AgentOutputError):
        adapter.execute(_request())


def test_empty_output_raises_agent_output_error() -> None:
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout="", stderr=""))
    adapter = CodexAdapter(_profile(), runner, PromptBuilder(max_prompt_characters=10000))  # type: ignore[arg-type]

    with pytest.raises(AgentOutputError):
        adapter.execute(_request())


def test_error_event_with_auth_wording_is_classified_as_authentication_failure() -> None:
    stdout = _jsonl({"type": "error", "message": "Not logged in. Run `codex login`."})
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout=stdout, stderr=""))
    adapter = CodexAdapter(_profile(), runner, PromptBuilder(max_prompt_characters=10000))  # type: ignore[arg-type]

    with pytest.raises(AgentAuthenticationError):
        adapter.execute(_request())


def test_check_authentication_recognizes_logged_in_text() -> None:
    runner = FakeProcessRunner(
        result=ProcessResult(exit_code=0, stdout="Logged in as someone@example.com", stderr="")
    )
    adapter = CodexAdapter(_profile(), runner, PromptBuilder(max_prompt_characters=10000))  # type: ignore[arg-type]

    assert adapter.check_authentication() is AuthenticationStatus.AUTHENTICATED


def test_check_authentication_recognizes_not_logged_in_text() -> None:
    runner = FakeProcessRunner(
        result=ProcessResult(exit_code=0, stdout="Not logged in.", stderr="")
    )
    adapter = CodexAdapter(_profile(), runner, PromptBuilder(max_prompt_characters=10000))  # type: ignore[arg-type]

    assert adapter.check_authentication() is AuthenticationStatus.UNAUTHENTICATED
