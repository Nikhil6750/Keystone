"""Shared, keyword-based error classification for local CLI provider adapters.

Each provider CLI reports authentication/usage/permission failures in its own
prose, and none of the three providers integrated in Phase 6A.1 documents a
stable machine-readable error-code contract for print/headless mode. This
module is a best-effort, defensive classifier over a CLI's own stdout/stderr
text — it is deliberately conservative (falls back to a generic process
error rather than guessing) and is the single place this heuristic lives, so
it is never duplicated per adapter.
"""

_AUTH_KEYWORDS = (
    "not logged in",
    "not authenticated",
    "please log in",
    "please login",
    "run 'claude auth login'",
    "run `claude auth login`",
    "codex login",
    "please run login",
    "unauthorized",
    "invalid api key",
    "authentication required",
    "auth status",
    "sign in",
)

_USAGE_LIMIT_KEYWORDS = (
    "usage limit",
    "rate limit",
    "rate-limit",
    "quota",
    "too many requests",
    "429",
    "overloaded",
)

_PERMISSION_KEYWORDS = (
    "permission denied",
    "approval required",
    "requires approval",
    "not permitted",
    "denied by policy",
)


def matches_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in keywords)


def looks_like_authentication_failure(text: str) -> bool:
    return matches_any(text, _AUTH_KEYWORDS)


def looks_like_usage_limit_failure(text: str) -> bool:
    return matches_any(text, _USAGE_LIMIT_KEYWORDS)


def looks_like_permission_failure(text: str) -> bool:
    return matches_any(text, _PERMISSION_KEYWORDS)
