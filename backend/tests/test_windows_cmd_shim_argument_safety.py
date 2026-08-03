"""Regression test for a real bug this phase's live verification caught:

On Windows, `shutil.which("claude")` resolves to an npm `.CMD` batch shim.
Passing a real, multi-line prompt (every prompt `PromptBuilder` builds embeds
newlines) as a trailing CLI argument to a `.cmd`/`.bat` target causes Windows
to route the process through `cmd.exe`'s own argument re-parsing, which
reliably corrupts multi-line arguments — confirmed by a real Keystone workflow
execution during this phase's live verification: Claude Code received a
mangled prompt and replied "No JSON context was included in your message"
instead of following the actual instruction.

Sending the prompt via stdin instead sidesteps command-line parsing entirely
and was confirmed (by direct, live `claude` invocations during this phase) to
work reliably. `codex`/`gemini` also default to stdin. Antigravity is different:
the installed native `agy.exe` 1.1.10 defines `--print` as a value flag, so its
prompt must be the next discrete argument; omitting the value makes the CLI
mistake the next option for the prompt and ignore stdin.
"""

from app.adapters.types import PROMPT_PLACEHOLDER
from app.core.config import Settings


def test_claude_code_defaults_to_stdin_input_with_no_prompt_placeholder() -> None:
    settings = Settings()

    assert settings.claude_code_input_mode == "stdin"
    assert all(PROMPT_PLACEHOLDER not in arg for arg in settings.claude_code_arguments)


def test_codex_defaults_to_safe_noninteractive_jsonl_mode() -> None:
    settings = Settings()

    assert settings.codex_arguments[:2] == ["exec", "--json"]
    assert "--ephemeral" in settings.codex_arguments
    sandbox_index = settings.codex_arguments.index("--sandbox")
    assert settings.codex_arguments[sandbox_index + 1] == "read-only"
    assert settings.codex_input_mode == "stdin"
    assert settings.codex_output_mode == "json_lines"
    assert all(PROMPT_PLACEHOLDER not in arg for arg in settings.codex_arguments)


def test_antigravity_defaults_to_prompt_argument_with_exact_placeholder() -> None:
    settings = Settings()

    assert settings.antigravity_input_mode == "prompt_argument"
    assert settings.antigravity_arguments.count(PROMPT_PLACEHOLDER) == 1


def test_claude_code_profile_builds_successfully_with_stdin_defaults() -> None:
    settings = Settings(claude_code_enabled=True)

    profile = settings.claude_code_profile()

    assert profile.input_mode.value == "stdin"


def test_antigravity_profile_builds_successfully_with_prompt_argument_defaults() -> None:
    settings = Settings(antigravity_enabled=True)

    profile = settings.antigravity_profile()

    assert profile.input_mode.value == "prompt_argument"


def test_antigravity_1_1_10_binds_prompt_value_to_print_flag() -> None:
    """`agy --print` is a value flag; stdin is not the print prompt in 1.1.10."""
    settings = Settings()

    assert settings.antigravity_input_mode == "prompt_argument"
    print_index = settings.antigravity_arguments.index("--print")
    assert settings.antigravity_arguments[print_index + 1] == PROMPT_PLACEHOLDER
    assert "--sandbox" in settings.antigravity_arguments
    assert settings.antigravity_arguments[:2] == ["--output-format", "json"]
