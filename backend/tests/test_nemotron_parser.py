"""Tests for `app.integrations.nemotron.parser`."""

import pytest

from app.engine.manager.models import ManagerResponse
from app.integrations.nemotron.errors import NemotronResponseError
from app.integrations.nemotron.parser import (
    decode_json_object,
    extract_final_content,
    parse_chat_completion_to_manager_response,
)


def _payload(content: str, *, tool_calls: list[object] | None = None) -> dict[str, object]:
    message: dict[str, object] = {"content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message}]}


# --- extract_final_content --------------------------------------------------


def test_extract_final_content_happy_path() -> None:
    assert extract_final_content(_payload("hello")) == "hello"


def test_extract_final_content_rejects_missing_choices() -> None:
    with pytest.raises(NemotronResponseError, match="choices"):
        extract_final_content({})


def test_extract_final_content_rejects_empty_choices() -> None:
    with pytest.raises(NemotronResponseError, match="choices"):
        extract_final_content({"choices": []})


def test_extract_final_content_rejects_non_list_choices() -> None:
    with pytest.raises(NemotronResponseError):
        extract_final_content({"choices": "not-a-list"})


def test_extract_final_content_rejects_non_object_choice() -> None:
    with pytest.raises(NemotronResponseError):
        extract_final_content({"choices": ["not-an-object"]})


def test_extract_final_content_rejects_non_object_message() -> None:
    with pytest.raises(NemotronResponseError):
        extract_final_content({"choices": [{"message": "not-an-object"}]})


def test_extract_final_content_rejects_missing_content() -> None:
    with pytest.raises(NemotronResponseError, match="content"):
        extract_final_content({"choices": [{"message": {}}]})


def test_extract_final_content_rejects_non_string_content() -> None:
    with pytest.raises(NemotronResponseError, match="content"):
        extract_final_content(_payload(content=123))  # type: ignore[arg-type]


def test_extract_final_content_rejects_empty_content() -> None:
    with pytest.raises(NemotronResponseError, match="empty"):
        extract_final_content(_payload("   "))


def test_extract_final_content_rejects_unexpected_tool_calls() -> None:
    payload = _payload("hello", tool_calls=[{"id": "call_1", "type": "function"}])
    with pytest.raises(NemotronResponseError, match="tool_calls"):
        extract_final_content(payload)


def test_extract_final_content_allows_empty_tool_calls_list() -> None:
    """An empty `tool_calls: []` list is not "unexpected tool calls" -- many
    providers include the key with an empty list even when no tool was
    invoked."""
    payload = _payload("hello", tool_calls=[])
    assert extract_final_content(payload) == "hello"


# --- reasoning / CoT safety --------------------------------------------------


def test_reasoning_content_is_never_extracted() -> None:
    payload = _payload("final answer")
    payload["choices"][0]["message"]["reasoning_content"] = "secret internal reasoning"  # type: ignore[index]
    assert extract_final_content(payload) == "final answer"


def test_think_tags_in_content_are_not_stripped_but_not_specially_read_either() -> None:
    """`extract_final_content` returns exactly `content` verbatim -- it is
    `decode_json_object`'s strictness (not a think-tag stripper) that
    rejects anything that isn't clean JSON, which is what actually keeps a
    provider's think-tagged prose out of a ManagerResponse."""
    content = "<think>secret reasoning</think>{\"request_id\": \"r1\"}"
    assert extract_final_content(_payload(content)) == content
    with pytest.raises(NemotronResponseError):
        decode_json_object(content)


def test_reasoning_content_never_appears_in_a_raised_error_message() -> None:
    payload = _payload("")
    payload["choices"][0]["message"]["reasoning_content"] = "SECRET_REASONING_MARKER"  # type: ignore[index]
    with pytest.raises(NemotronResponseError) as excinfo:
        extract_final_content(payload)
    assert "SECRET_REASONING_MARKER" not in str(excinfo.value)


# --- decode_json_object -------------------------------------------------


def test_decode_json_object_strict() -> None:
    assert decode_json_object('{"request_id": "r1"}') == {"request_id": "r1"}


def test_decode_json_object_rejects_malformed_json() -> None:
    with pytest.raises(NemotronResponseError):
        decode_json_object("{not valid json")


def test_decode_json_object_rejects_truncated_json() -> None:
    with pytest.raises(NemotronResponseError):
        decode_json_object('{"request_id": "r1"')


def test_decode_json_object_rejects_non_object_json() -> None:
    with pytest.raises(NemotronResponseError):
        decode_json_object("[1, 2, 3]")
    with pytest.raises(NemotronResponseError):
        decode_json_object('"just a string"')


def test_decode_json_object_extracts_single_fenced_json_block() -> None:
    content = '```json\n{"request_id": "r1"}\n```'
    assert decode_json_object(content) == {"request_id": "r1"}


def test_decode_json_object_extracts_fenced_block_without_json_language_tag() -> None:
    content = '```\n{"request_id": "r1"}\n```'
    assert decode_json_object(content) == {"request_id": "r1"}


def test_decode_json_object_rejects_prose_around_fenced_block() -> None:
    content = 'Here is the answer:\n```json\n{"request_id": "r1"}\n```'
    with pytest.raises(NemotronResponseError):
        decode_json_object(content)


def test_decode_json_object_rejects_multiple_fenced_blocks() -> None:
    content = '```json\n{"a": 1}\n```\n```json\n{"b": 2}\n```'
    with pytest.raises(NemotronResponseError):
        decode_json_object(content)


def test_decode_json_object_rejects_fenced_block_with_invalid_inner_json() -> None:
    content = "```json\nnot valid json\n```"
    with pytest.raises(NemotronResponseError):
        decode_json_object(content)


# --- full pipeline ------------------------------------------------------


def test_parse_chat_completion_to_manager_response_success() -> None:
    payload = _payload('{"request_id": "r1", "goal_interpretation": "build X"}')
    response = parse_chat_completion_to_manager_response(payload)
    assert isinstance(response, ManagerResponse)
    assert response.request_id == "r1"


def test_parse_chat_completion_to_manager_response_schema_invalid() -> None:
    from app.engine.manager.errors import ManagerInvalidResponseError

    payload = _payload('{"request_id": "r1", "confidence": 5.0}')
    with pytest.raises(ManagerInvalidResponseError):
        parse_chat_completion_to_manager_response(payload)


def test_parse_chat_completion_to_manager_response_rejects_extra_unknown_field() -> None:
    from app.engine.manager.errors import ManagerInvalidResponseError

    payload = _payload('{"request_id": "r1", "chain_of_thought": "leak"}')
    with pytest.raises(ManagerInvalidResponseError):
        parse_chat_completion_to_manager_response(payload)


def test_parse_chat_completion_to_manager_response_is_deterministic() -> None:
    payload = _payload('{"request_id": "r1"}')
    results = [parse_chat_completion_to_manager_response(payload) for _ in range(10)]
    assert all(result == results[0] for result in results)
