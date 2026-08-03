"""Local CLI adapter for the installed `agy` (Google Antigravity) command.

Canonical type `antigravity`, executable `agy` — a separate, Gemini-*powered*
local coding agent, distinct from the standalone Gemini CLI (`gemini`). Uses
whatever authenticated session the locally installed CLI already has — no
API key, no stored credentials, no HTTP calls, no keyring read, and no
`/logout` is ever invoked. Always invokes headless mode (`-p`/
`--output-format json`) — never the interactive TUI — from a backend
request.

Live-verified against `agy.exe` 1.1.10, which returns a single JSON object
whose final text is under `response` and whose safe metadata includes status,
conversation ID, timing, turns, and usage. There is no
documented, safe, dedicated authentication-status command for this CLI, so
`check_authentication` always reports `unknown`; only `verify_connection`
(a real headless call) can positively confirm authentication.
"""

import json
from typing import Any

from app.adapters.base import build_agent_result
from app.adapters.error_classification import (
    looks_like_authentication_failure,
    looks_like_permission_failure,
    looks_like_usage_limit_failure,
)
from app.adapters.exceptions import (
    AgentAuthenticationError,
    AgentOutputError,
    AgentPermissionError,
    AgentUsageLimitError,
)
from app.adapters.local_cli import LocalCLIAdapter
from app.adapters.process_runner import ProcessResult

_CONTENT_KEYS = ("result", "content", "text", "output", "response", "message")


class AntigravityAdapter(LocalCLIAdapter):
    """Executes workflow steps via the local `agy` CLI in headless JSON mode."""

    def _build_result(self, result: ProcessResult) -> dict[str, Any]:
        stdout = result.stdout.strip()
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise AgentOutputError("antigravity produced output that was not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise AgentOutputError("antigravity's JSON output was not an object")

        is_error = bool(parsed.get("is_error") or parsed.get("error"))
        if is_error:
            error_text = str(parsed.get("error") or parsed.get("message") or "unknown error")
            self._classify_and_raise(error_text)

        content_text = None
        for key in _CONTENT_KEYS:
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                content_text = value.strip()
                break

        if not content_text:
            raise AgentOutputError("antigravity produced no recognizable result text")

        return build_agent_result(
            agent_type=self._profile.agent_type,
            content=content_text,
            execution_mode="local_cli",
            extra_metadata={
                "provider_session_id": parsed.get("session_id"),
                "model": parsed.get("model"),
            },
        )

    @staticmethod
    def _classify_and_raise(text: str) -> None:
        """Best-effort classification of the provider's sanitized error text."""
        if looks_like_authentication_failure(text):
            raise AgentAuthenticationError(
                "Google Antigravity reported an authentication failure. Run "
                "`agy` locally and complete the official browser sign-in."
            )
        if looks_like_usage_limit_failure(text):
            raise AgentUsageLimitError("Google Antigravity reported a usage or rate limit.")
        if looks_like_permission_failure(text):
            raise AgentPermissionError(
                "Google Antigravity requires a permission only a human can grant."
            )
        raise AgentOutputError(f"antigravity reported an error: {text.strip()[:200]}")
