"""Shared evidence-value safety check: reject reserved reasoning-trace-shaped
dict keys anywhere inside an observable-evidence value.

Used by `app.contracts.verification` and `app.contracts.explainability` — a
single shared helper rather than duplicated logic in each, so the reserved
key vocabulary and matching rule stay defined in exactly one place. This
module has no dependency on either of those (or on anything else in
`app.contracts`), so it can sit below both without creating a cycle.

**What this checks:** dict keys, recursively through nested dicts and
lists/tuples, matched by exact name after normalizing case and separator
style (`-`/` ` folded to `_`) — never by substring. `reasoning_step_count`
(a benign observable count) is accepted; `chain_of_thought`, however deeply
nested or list-wrapped, is rejected.

**What this does NOT check:** free-text string fields (`summary`,
`description`, `reason_text`, `failure_reason`, etc.). Reasoning content
pasted directly into a string is invisible to a key-based check by
construction. Every contract with such a field is documented as
caller-controlled: it must be populated only with Keystone's own observable
decision evidence, never a model's internal reasoning, and that discipline
is enforced by design review and code review, not by this function. See
`docs/contracts.md` for the full rule this helper partially automates.
"""

from typing import Any

_RESERVED_REASONING_KEYS: frozenset[str] = frozenset(
    {
        "chain_of_thought",
        "hidden_reasoning",
        "reasoning_trace",
        "internal_reasoning",
        "private_reasoning",
        "internal_thought",
        "hidden_prompt",
        "raw_prompt",
        "scratchpad",
    }
)


def _normalize_key(key: Any) -> str:
    return str(key).strip().lower().replace("-", "_").replace(" ", "_")


def _walk(node: Any) -> None:
    if isinstance(node, dict):
        for key, nested in node.items():
            normalized = _normalize_key(key)
            if normalized in _RESERVED_REASONING_KEYS:
                raise ValueError(
                    f"evidence value must not contain a '{key}' key — Keystone explains only "
                    "its own observable decision evidence, never a model's internal reasoning"
                )
            _walk(nested)
    elif isinstance(node, list | tuple):
        for item in node:
            _walk(item)


def reject_reasoning_shaped_keys(value: Any) -> Any:
    """Recursively reject reserved reasoning-trace-shaped dict keys in `value`.

    Walks dicts and lists/tuples at any depth. Raises `ValueError` on the
    first reserved key found (exact match after normalization — see module
    docstring); otherwise returns `value` unchanged, for direct use as a
    Pydantic `field_validator` body.
    """
    _walk(value)
    return value


__all__ = ["reject_reasoning_shaped_keys"]
