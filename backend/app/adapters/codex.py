"""Local CLI adapter for the installed `codex` command.

Uses whatever authenticated session the locally installed CLI already has
(subscription-based login) — no API key, no stored credentials, no HTTP
calls. Always invokes `codex exec --json "<prompt>"` — never the interactive
TUI — from a backend request.

IMPORTANT: `codex` was not installed in the environment this adapter was
built in, so this JSONL parser is modeled on Codex's publicly documented
`exec --json` event-stream conventions (a stream of `{"type": ...}` event
objects, ending in a final agent-message event), not captured from a live
run. Treat it as best-effort until it has been exercised against a real
installation — see `docs/live-agent-connectors.md`'s known-limitations
section.
"""

import json
from typing import Any

from app.adapters.base import build_agent_result
from app.adapters.connection import AuthenticationStatus
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

_AUTH_STATUS_TIMEOUT_SECONDS = 10.0
_AUTH_STATUS_MAX_OUTPUT_CHARACTERS = 2000

# Event `type` values that, per Codex's documented JSON event stream, may
# carry the final user-visible agent message. Checked in order.
_MESSAGE_ITEM_TYPES = ("agent_message", "assistant_message")


class CodexAdapter(LocalCLIAdapter):
    """Executes workflow steps via `codex exec --json`."""

    def _build_result(self, result: ProcessResult) -> dict[str, Any]:
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            raise AgentOutputError("codex produced no JSONL output")

        events: list[dict[str, Any]] = []
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue  # ignore a stray non-JSON progress line, never fail on it alone
            if isinstance(event, dict):
                events.append(event)

        if not events:
            raise AgentOutputError("codex produced no parsable JSON events")

        for event in events:
            if event.get("type") == "error":
                message = str(event.get("message", "codex reported an error"))
                self._classify_and_raise(message)

        message_text = _extract_final_message(events)
        if not message_text:
            combined = " ".join(json.dumps(e, sort_keys=True) for e in events[-3:])
            raise AgentOutputError(
                f"codex produced no final agent message in its event stream: {combined[:200]}"
            )

        thread_id = next(
            (event.get("thread_id") for event in events if event.get("thread_id")), None
        )
        return build_agent_result(
            agent_type=self._profile.agent_type,
            content=message_text,
            execution_mode="local_cli",
            extra_metadata={"provider_session_id": thread_id},
        )

    @staticmethod
    def _classify_and_raise(text: str) -> None:
        """Best-effort classification — see module docstring: not verified
        against a real Codex installation in this environment."""
        if looks_like_authentication_failure(text):
            raise AgentAuthenticationError(
                "Codex reported an authentication failure. Run `codex login` locally."
            )
        if looks_like_usage_limit_failure(text):
            raise AgentUsageLimitError("Codex reported a usage or rate limit.")
        if looks_like_permission_failure(text):
            raise AgentPermissionError("Codex requires a sandbox/approval only a human can grant.")
        raise AgentOutputError(f"codex reported an error: {text.strip()[:200]}")

    def check_authentication(self) -> AuthenticationStatus:
        """Runs `codex login status`. Parsing is best-effort text matching
        (no confirmed real JSON schema for this exact command in the
        installed-version environment this adapter was built in)."""
        try:
            result = self._process_runner.run(
                self._profile.executable,
                ["login", "status"],
                stdin_text=None,
                timeout_seconds=_AUTH_STATUS_TIMEOUT_SECONDS,
                max_output_characters=_AUTH_STATUS_MAX_OUTPUT_CHARACTERS,
            )
        except Exception:  # noqa: BLE001 - any failure here is just "unknown", never fatal
            return AuthenticationStatus.UNKNOWN

        text = (result.stdout + " " + result.stderr).lower()
        if "logged in" in text and "not logged in" not in text:
            return AuthenticationStatus.AUTHENTICATED
        if "not logged in" in text or looks_like_authentication_failure(text):
            return AuthenticationStatus.UNAUTHENTICATED
        return AuthenticationStatus.UNKNOWN


def _extract_final_message(events: list[dict[str, Any]]) -> str | None:
    for event in reversed(events):
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") in _MESSAGE_ITEM_TYPES:
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
        if event.get("type") in _MESSAGE_ITEM_TYPES:
            text = event.get("text") or event.get("message")
            if isinstance(text, str) and text.strip():
                return text.strip()
    return None
