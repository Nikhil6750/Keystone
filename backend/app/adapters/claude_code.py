"""Local CLI adapter for the installed `claude` (Claude Code) command.

Uses whatever authenticated session the locally installed CLI already has
(subscription-based login) — no API key, no stored credentials, no HTTP
calls. Never invokes interactive Claude Code from an API request — always
`-p`/`--print` with `--output-format json`.

Verified live against Claude Code 2.1.154: `claude -p "<prompt>"
--output-format json` returns a single JSON object shaped roughly as
`{"type": "result", "subtype": "success", "is_error": false,
"result": "<final text>", "session_id": "...", "duration_ms": ...}`
(additional cost/usage fields are present but never surfaced past this
adapter). Only `result`, `session_id`, and `duration_ms` are read.
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


class ClaudeCodeAdapter(LocalCLIAdapter):
    """Executes workflow steps via the local `claude` CLI."""

    def _build_result(self, result: ProcessResult) -> dict[str, Any]:
        stdout = result.stdout.strip()
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise AgentOutputError("claude produced output that was not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise AgentOutputError("claude's JSON output was not an object")

        is_error = bool(parsed.get("is_error", False))
        subtype = str(parsed.get("subtype", ""))
        result_text = parsed.get("result")
        combined_text = f"{subtype} {result_text or ''} {result.stderr}"

        if is_error:
            self._classify_and_raise(combined_text)

        if not isinstance(result_text, str) or not result_text.strip():
            raise AgentOutputError("claude produced no final result text", retryable=False)

        return build_agent_result(
            agent_type=self._profile.agent_type,
            content=result_text.strip(),
            execution_mode="local_cli",
            extra_metadata={
                "provider_session_id": parsed.get("session_id"),
                "duration_ms": parsed.get("duration_ms"),
            },
        )

    @staticmethod
    def _classify_and_raise(text: str) -> None:
        """Best-effort classification of a Claude Code `is_error: true`
        result. Claude Code's print-mode JSON does not document a stable
        machine-readable error-code contract, so this is a defensive keyword
        heuristic over the subtype/result/stderr text, not an exhaustive,
        live-verified mapping of every failure mode."""
        if looks_like_authentication_failure(text):
            raise AgentAuthenticationError(
                "Claude Code reported an authentication failure. Run "
                "`claude auth login` locally to re-authenticate."
            )
        if looks_like_usage_limit_failure(text):
            raise AgentUsageLimitError("Claude Code reported a usage or rate limit.")
        if looks_like_permission_failure(text):
            raise AgentPermissionError(
                "Claude Code requires a permission/approval only a human can grant."
            )
        raise AgentOutputError(f"claude reported an error: {text.strip()[:200]}")

    def check_authentication(self) -> AuthenticationStatus:
        """Runs `claude auth status` and reads only the safe `loggedIn`
        boolean — the email, org ID, org name, and subscription type this
        command also returns are read by nothing here and never persisted
        or logged."""
        try:
            result = self._process_runner.run(
                self._profile.executable,
                ["auth", "status"],
                stdin_text=None,
                timeout_seconds=_AUTH_STATUS_TIMEOUT_SECONDS,
                max_output_characters=_AUTH_STATUS_MAX_OUTPUT_CHARACTERS,
            )
        except Exception:  # noqa: BLE001 - any failure here is just "unknown", never fatal
            return AuthenticationStatus.UNKNOWN

        try:
            parsed = json.loads(result.stdout.strip())
        except json.JSONDecodeError:
            return AuthenticationStatus.UNKNOWN
        if not isinstance(parsed, dict) or "loggedIn" not in parsed:
            return AuthenticationStatus.UNKNOWN
        return (
            AuthenticationStatus.AUTHENTICATED
            if parsed["loggedIn"]
            else AuthenticationStatus.UNAUTHENTICATED
        )
