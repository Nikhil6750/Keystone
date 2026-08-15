"""Workspace-root validation for local CLI agent adapters.

Two independent validators, for two different trust models:

- `resolve_workspace_directory` (original): a defense-in-depth primitive
  for a single, server-configured `KEYSTONE_AGENT_WORKSPACE_ROOT` that
  every requested directory must nest under. Not currently wired to any
  caller; kept for a future feature that wants exactly that fixed-root
  model.
- `validate_workspace_root` (Stage 8C.3): validates a client-supplied
  execution workspace -- normally the user's own currently open VS Code
  workspace folder, passed through `OrchestrationRequest.workspace_root`
  -- with no fixed root of its own; see its own docstring.
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


_MAX_WORKSPACE_ROOT_LENGTH = 4096


def validate_workspace_root(requested: str) -> str:
    """Validate a client-supplied execution workspace (Stage 8C.3: a real
    coding agent's subprocess `cwd`, typically the user's own currently
    open VS Code workspace folder) -- server-side, since client-side
    validation alone is never a security boundary.

    Unlike `resolve_workspace_directory` above, there is no single fixed
    `workspace_root` every request must nest under: whichever folder the
    user has genuinely opened *is* the trusted boundary here, the same way
    it would be for any local dev tool the user runs directly inside that
    folder. What's still enforced, always:

    - not blank, not absurdly long
    - already absolute as given (never silently resolved relative to this
      *server* process's own cwd -- that would let a relative path mean
      something the client never intended)
    - resolves (symlinks/`..` normalized) to a path that genuinely exists
      and is a directory right now

    Raises `WorkspaceValidationError` for any violation. Returns the
    resolved, normalized absolute path as a string.
    """
    cleaned = requested.strip()
    if not cleaned:
        raise WorkspaceValidationError("workspace_root must not be blank")
    if len(cleaned) > _MAX_WORKSPACE_ROOT_LENGTH:
        raise WorkspaceValidationError(
            f"workspace_root exceeds maximum length ({_MAX_WORKSPACE_ROOT_LENGTH})"
        )

    candidate = Path(cleaned)
    if not candidate.is_absolute():
        raise WorkspaceValidationError(f"workspace_root '{cleaned}' must be an absolute path")

    resolved = candidate.resolve()
    if not resolved.exists():
        raise WorkspaceValidationError(f"workspace_root '{resolved}' does not exist")
    if not resolved.is_dir():
        raise WorkspaceValidationError(f"workspace_root '{resolved}' is not a directory")

    return str(resolved)
