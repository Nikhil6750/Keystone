"""Regression test for the Stage 8C.3 headless-permission fix.

Live-verified against Claude Code CLI 2.1.154: without `--permission-mode
acceptEdits`, a headless `-p` call has no human to approve a Write/Edit
tool call, so the CLI silently skips the file write while still returning
`is_error: false` and a plausible-sounding text result -- a real coding
task reports success and produces zero files. This guards the default
configuration against a silent revert of that fix.
"""

from app.core.config import Settings


def test_claude_code_default_arguments_include_accept_edits_permission_mode() -> None:
    settings = Settings()
    assert "--permission-mode" in settings.claude_code_arguments
    idx = settings.claude_code_arguments.index("--permission-mode")
    assert settings.claude_code_arguments[idx + 1] == "acceptEdits"


def test_claude_code_profile_carries_the_permission_mode_argument() -> None:
    settings = Settings(claude_code_enabled=True, claude_code_executable="claude")
    profile = settings.claude_code_profile()
    assert "--permission-mode" in profile.arguments
    assert "acceptEdits" in profile.arguments
