"""Local CLI adapter for the installed `agy` (Google Antigravity) command.

Canonical type `antigravity`, executable `agy` — a separate, Gemini-*powered*
local coding agent, distinct from the standalone Gemini CLI (`gemini`). Uses
whatever authenticated session the locally installed CLI already has — no
API key, no stored credentials, no HTTP calls, no keyring read, and no
`/logout` is ever invoked. Always invokes headless mode (`-p <prompt>`) —
never the interactive TUI — from a backend request.

Live-verified against `agy.exe` 1.1.10, which returns plain text for this
invocation. There is no documented, safe, dedicated authentication-status
command for this CLI, so
`check_authentication` always reports `unknown`; only `verify_connection`
(a real headless call) can positively confirm authentication.
"""

from app.adapters.local_cli import LocalCLIAdapter


class AntigravityAdapter(LocalCLIAdapter):
    """Executes workflow steps through the shared local-CLI argv boundary."""
