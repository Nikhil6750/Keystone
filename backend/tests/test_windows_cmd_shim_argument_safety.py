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
work reliably. `codex`/`gemini` already defaulted to stdin; this locks in the
same default for `claude_code` and `antigravity` so it can never silently
regress back to `prompt_argument`.
"""

from app.adapters.types import PROMPT_PLACEHOLDER
from app.core.config import Settings


def test_claude_code_defaults_to_stdin_input_with_no_prompt_placeholder() -> None:
    settings = Settings()

    assert settings.claude_code_input_mode == "stdin"
    assert all(PROMPT_PLACEHOLDER not in arg for arg in settings.claude_code_arguments)


def test_antigravity_defaults_to_stdin_input_with_no_prompt_placeholder() -> None:
    settings = Settings()

    assert settings.antigravity_input_mode == "stdin"
    assert all(PROMPT_PLACEHOLDER not in arg for arg in settings.antigravity_arguments)


def test_claude_code_profile_builds_successfully_with_stdin_defaults() -> None:
    settings = Settings(claude_code_enabled=True)

    profile = settings.claude_code_profile()

    assert profile.input_mode.value == "stdin"


def test_antigravity_profile_builds_successfully_with_stdin_defaults() -> None:
    settings = Settings(antigravity_enabled=True)

    profile = settings.antigravity_profile()

    assert profile.input_mode.value == "stdin"
