"""Workspace-root validation for local CLI agent adapters.

A defense-in-depth primitive: resolves a requested working directory to an
absolute, canonical path and confirms it stays within the configured
`KEYSTONE_AGENT_WORKSPACE_ROOT`, rejecting path traversal or an unrelated
filesystem root. Workflow payloads never supply a working directory directly
today (`StepExecutionRequest` carries no such field) — this exists so that if
a future, explicitly-trusted feature ever needs to pick a working directory
per step, it is validated the same way everywhere rather than duplicated.
"""

from pathlib import Path


class WorkspaceValidationError(ValueError):
    """Raised when a requested working directory is outside the configured workspace root."""


def resolve_workspace_directory(requested: str | None, workspace_root: str) -> Path:
    """Resolve `requested` (or the root itself, if `None`) to an absolute path
    that is confirmed to be the workspace root or a descendant of it.

    Raises `WorkspaceValidationError` for path traversal or any path outside
    `workspace_root`, including a resolved-but-nonexistent ancestor mismatch.
    """
    root = Path(workspace_root).resolve()
    candidate = root if requested is None else Path(requested)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()

    if resolved != root and root not in resolved.parents:
        raise WorkspaceValidationError(
            f"working directory '{resolved}' is outside the configured workspace root '{root}'"
        )
    return resolved
