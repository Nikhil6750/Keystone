"""Shared adapter result-envelope construction."""

from typing import Any

from app.adapters.exceptions import AgentOutputError


def build_agent_result(
    *,
    agent_type: str,
    content: str,
    execution_mode: str,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the stable `{"agent_type", "content", "metadata": {...}}` result envelope.

    Raises `AgentOutputError` if `content` is empty.
    """
    if not content:
        raise AgentOutputError("agent produced an empty result")

    metadata: dict[str, Any] = {"execution_mode": execution_mode}
    if extra_metadata:
        metadata.update(extra_metadata)
    return {"agent_type": agent_type, "content": content, "metadata": metadata}
