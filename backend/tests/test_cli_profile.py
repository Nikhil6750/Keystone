"""Tests for `CLIProfile` construction and validation."""

import pytest

from app.adapters.types import (
    InputMode,
    OutputMode,
    create_cli_profile,
    parse_input_mode,
    parse_output_mode,
)


def _valid_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "agent_type": "claude_code",
        "enabled": True,
        "executable": "claude",
        "arguments": ["-p", "--output-format", "json", "{prompt}"],
        "input_mode": "prompt_argument",
        "output_mode": "json",
        "timeout_seconds": 30.0,
        "max_output_characters": 1000,
    }
    base.update(overrides)
    return base


def test_blank_executable_is_rejected() -> None:
    with pytest.raises(ValueError, match="executable"):
        create_cli_profile(**_valid_kwargs(executable="   "))  # type: ignore[arg-type]


def test_negative_timeout_is_rejected() -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        create_cli_profile(**_valid_kwargs(timeout_seconds=-1.0))  # type: ignore[arg-type]


def test_zero_timeout_is_rejected() -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        create_cli_profile(**_valid_kwargs(timeout_seconds=0.0))  # type: ignore[arg-type]


def test_invalid_input_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="input_mode"):
        create_cli_profile(**_valid_kwargs(input_mode="bogus"))  # type: ignore[arg-type]


def test_invalid_output_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="output_mode"):
        create_cli_profile(**_valid_kwargs(output_mode="bogus"))  # type: ignore[arg-type]


def test_unsafe_shell_string_configuration_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsafe"):
        create_cli_profile(
            **_valid_kwargs(arguments=["-p", "{prompt} && rm -rf /"])  # type: ignore[arg-type]
        )


def test_invalid_prompt_placeholder_is_rejected_for_stdin_mode() -> None:
    with pytest.raises(ValueError, match="prompt_argument"):
        create_cli_profile(
            **_valid_kwargs(input_mode="stdin", arguments=["{prompt}"])  # type: ignore[arg-type]
        )


def test_missing_prompt_placeholder_is_rejected_for_prompt_argument_mode() -> None:
    with pytest.raises(ValueError, match="placeholder"):
        create_cli_profile(**_valid_kwargs(arguments=["-p"]))  # type: ignore[arg-type]


def test_more_than_one_prompt_placeholder_is_rejected() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        create_cli_profile(
            **_valid_kwargs(arguments=["{prompt}", "{prompt}"])  # type: ignore[arg-type]
        )


def test_json_argument_settings_parse_correctly() -> None:
    profile = create_cli_profile(**_valid_kwargs())  # type: ignore[arg-type]
    assert profile.arguments == ["-p", "--output-format", "json", "{prompt}"]
    assert profile.input_mode is InputMode.PROMPT_ARGUMENT
    assert profile.output_mode is OutputMode.JSON


def test_parse_input_mode_accepts_valid_values() -> None:
    assert parse_input_mode("stdin") is InputMode.STDIN
    assert parse_input_mode("prompt_argument") is InputMode.PROMPT_ARGUMENT


def test_parse_output_mode_accepts_valid_values() -> None:
    assert parse_output_mode("text") is OutputMode.TEXT
    assert parse_output_mode("json") is OutputMode.JSON
    assert parse_output_mode("json_lines") is OutputMode.JSON_LINES


def test_stdin_mode_with_no_placeholder_is_valid() -> None:
    profile = create_cli_profile(
        **_valid_kwargs(input_mode="stdin", output_mode="text", arguments=["--flag"])  # type: ignore[arg-type]
    )
    assert profile.input_mode is InputMode.STDIN
