"""Local CLI adapter for the installed `claude` (Claude Code) command.

Uses whatever authenticated session the locally installed CLI already has
(subscription-based login) — no API key, no stored credentials, no HTTP calls.
"""

from app.adapters.local_cli import LocalCLIAdapter


class ClaudeCodeAdapter(LocalCLIAdapter):
    """Executes workflow steps via the local `claude` CLI."""
