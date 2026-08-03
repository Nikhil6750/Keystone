"""Local CLI adapter for the installed `codex` command.

Uses whatever authenticated session the locally installed CLI already has
(subscription-based login) — no API key, no stored credentials, no HTTP calls.
"""

from app.adapters.local_cli import LocalCLIAdapter


class CodexAdapter(LocalCLIAdapter):
    """Executes workflow steps via the local `codex` CLI."""
