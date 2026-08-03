"""Shared type definitions for local CLI agent adapters.

Profiles are built only from trusted application settings — never from
workflow payloads — via `create_cli_profile`, which is also the single place
that validates them.
"""

from dataclasses import dataclass
from enum import StrEnum

PROMPT_PLACEHOLDER = "{prompt}"

_UNSAFE_ARGUMENT_TOKENS = (";", "|", "&&", "&", "`", "$(", ">", "<")


class AgentType(StrEnum):
    """The four canonical agent types Keystone recognizes."""

    CLAUDE_CODE = "claude_code"
    CODEX = "codex"
    GEMINI = "gemini"
    DEMO = "demo"


class InputMode(StrEnum):
    STDIN = "stdin"
    PROMPT_ARGUMENT = "prompt_argument"


class OutputMode(StrEnum):
    TEXT = "text"
    JSON = "json"
    JSON_LINES = "json_lines"


def parse_input_mode(value: str) -> InputMode:
    try:
        return InputMode(value)
    except ValueError as exc:
        raise ValueError(f"invalid input_mode: '{value}'") from exc


def parse_output_mode(value: str) -> OutputMode:
    try:
        return OutputMode(value)
    except ValueError as exc:
        raise ValueError(f"invalid output_mode: '{value}'") from exc


@dataclass(frozen=True)
class CLIProfile:
    """Trusted, settings-derived configuration for one local CLI adapter."""

    agent_type: str
    enabled: bool
    executable: str
    arguments: list[str]
    input_mode: InputMode
    output_mode: OutputMode
    timeout_seconds: float
    max_output_characters: int


def create_cli_profile(
    *,
    agent_type: str,
    enabled: bool,
    executable: str,
    arguments: list[str],
    input_mode: str,
    output_mode: str,
    timeout_seconds: float,
    max_output_characters: int,
) -> CLIProfile:
    """Build and validate a `CLIProfile`. Raises `ValueError` for any unsafe or invalid input."""
    if not executable.strip():
        raise ValueError(f"{agent_type}: executable must not be blank")
    if timeout_seconds <= 0:
        raise ValueError(f"{agent_type}: timeout_seconds must be positive")
    if max_output_characters <= 0:
        raise ValueError(f"{agent_type}: max_output_characters must be positive")

    parsed_input_mode = parse_input_mode(input_mode)
    parsed_output_mode = parse_output_mode(output_mode)

    if not isinstance(arguments, list) or any(not isinstance(arg, str) for arg in arguments):
        raise ValueError(f"{agent_type}: arguments must be a list of strings")

    for arg in arguments:
        if any(token in arg for token in _UNSAFE_ARGUMENT_TOKENS):
            raise ValueError(
                f"{agent_type}: argument {arg!r} contains characters suggesting an unsafe "
                "shell-string configuration; pass discrete arguments instead"
            )

    placeholder_count = sum(arg.count(PROMPT_PLACEHOLDER) for arg in arguments)
    if parsed_input_mode is InputMode.PROMPT_ARGUMENT:
        if placeholder_count != 1:
            raise ValueError(
                f"{agent_type}: input_mode=prompt_argument requires exactly one "
                f"'{PROMPT_PLACEHOLDER}' placeholder in arguments, found {placeholder_count}"
            )
    elif placeholder_count > 0:
        raise ValueError(
            f"{agent_type}: '{PROMPT_PLACEHOLDER}' placeholder is only valid with "
            "input_mode=prompt_argument"
        )

    return CLIProfile(
        agent_type=agent_type,
        enabled=enabled,
        executable=executable,
        arguments=list(arguments),
        input_mode=parsed_input_mode,
        output_mode=parsed_output_mode,
        timeout_seconds=timeout_seconds,
        max_output_characters=max_output_characters,
    )
