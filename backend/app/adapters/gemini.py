"""Local CLI adapter for the installed `gemini` command.

Uses whatever authenticated session the locally installed CLI already has
(subscription-based login) — no API key, no stored credentials, no HTTP calls.
Represents only the locally installed Gemini CLI; it does not control any
other separate application.
"""

from app.adapters.local_cli import LocalCLIAdapter


class GeminiAdapter(LocalCLIAdapter):
    """Executes workflow steps via the local `gemini` CLI."""
