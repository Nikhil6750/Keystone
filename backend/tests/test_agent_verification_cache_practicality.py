"""Regression test for a real bug found during Phase 6A.1 manual frontend
verification: `/agents` correctly showed Claude Code, Codex, and Antigravity as
`connected` right after verification, but by the time the operator navigated
to `/chat` and reached the workflow-builder's agent dropdown, all three showed
"Not authenticated" and could not be selected.

Root cause: `KEYSTONE_AGENT_CONNECTION_CACHE_SECONDS` defaulted to 60 seconds.
Verifying three real providers sequentially through the browser, then reading
the page, then navigating to `/chat` and opening the workflow builder,
routinely took longer than that — so the freshly-fetched `GET /agents` call
the workflow builder makes on mount had already crossed the TTL and correctly
(per the *existing* cache-expiry logic) reported `authentication_status:
unknown` / `connection_status: verification_required`. This was never a stale
frontend cache or a `GET /agents` bug — `AgentConnectionCache.get()` and
`_cached_connection_fields()` both behaved exactly as designed; the *default
TTL itself* was simply too short for one realistic manual session.

This does not weaken the verification requirement: an agent still reverts to
`verification_required` once the (now longer) window elapses, and
`authentication_status` is still only ever set from a real verification
result — never inferred from `installation_status` alone.
"""

from app.core.config import Settings


def test_agent_connection_cache_default_is_practical_for_one_manual_session() -> None:
    settings = Settings()

    # Comfortably longer than the ~60s it just took to reproduce the bug
    # (verify three real providers via the browser, read the page, navigate
    # to /chat, and reach the agent dropdown), while still finite — this is
    # not "trust forever," it is "trust for one realistic session."
    assert settings.agent_connection_cache_seconds >= 300.0


def test_agent_connection_cache_still_expires_eventually() -> None:
    """The fix for practicality must never become "never expires" — that would
    remove the verification requirement entirely (forbidden by this phase's
    security constraints)."""
    settings = Settings()

    assert settings.agent_connection_cache_seconds < float("inf")
    assert settings.agent_connection_cache_seconds > 0.0
