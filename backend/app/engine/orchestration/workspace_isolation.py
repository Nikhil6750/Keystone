"""Git-worktree-based workspace isolation for concurrent orchestration runs
that target the same external repository (`OrchestrationRequest
.isolate_workspace`).

Scope, deliberately bounded: this isolates one orchestration *run*'s writes
from any other concurrently-running orchestration targeting the same
`workspace_root` -- e.g. two separate `POST /orchestrations` requests hitting
the same target repo at once, each building a different part of a project.
It does not isolate individual steps *within* one already-coordinated
workflow; those already carry ownership/parallel-safety metadata from the
planner (`TaskSpec.target_files_ownership`/`parallel_safe`, see
`app.engine.planning.compiler`), and `WorkflowEngine`'s own bounded
concurrency already schedules around it. Nesting per-step isolation inside
one workflow's own concurrent execution is a larger change to
`WorkflowEngine`/`GraphScheduler` themselves, out of scope here.

Conflict resolution on integration is also deliberately out of scope: a
merge conflict is surfaced as `WorkspaceIntegrationConflictError` for a
human (or a future repair cycle) to resolve. Keystone does not attempt
automatic conflict resolution in this stage.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass

from app.engine.orchestration.errors import (
    WorkspaceIntegrationConflictError,
    WorkspaceIsolationSetupError,
)

logger = logging.getLogger(__name__)

_GIT_TIMEOUT_SECONDS = 30.0
_CLEANUP_RETRY_ATTEMPTS = 5
_CLEANUP_RETRY_BASE_DELAY_SECONDS = 0.1
_STDERR_LIMIT = 300
_UNSAFE_BRANCH_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class IsolatedWorkspace:
    """One orchestration run's dedicated git worktree."""

    repo_root: str
    worktree_path: str
    branch_name: str
    base_branch: str


def _safe_branch_suffix(run_id: str) -> str:
    """Sanitize an arbitrary `request_id` into a valid, bounded git ref
    component (no spaces/colons/globs; no leading/trailing `-`/`.`)."""
    sanitized = _UNSAFE_BRANCH_CHARS.sub("-", run_id).strip("-.")
    return sanitized[:80] if sanitized else "run"


def _run_git(args: list[str], *, cwd: str) -> subprocess.CompletedProcess[str]:
    """Run one bounded, non-shell git command. Never raises -- an
    unresolvable `git` executable or a missing `cwd` is reported as a
    failed (`returncode=1`) result, exactly like any other git failure, so
    every call site can check `.returncode` uniformly."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_GIT_TIMEOUT_SECONDS,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(
            args=["git", *args], returncode=1, stdout="", stderr=str(exc)
        )


def is_git_repository(path: str) -> bool:
    """True iff `path` is inside a real git working tree (not a bare repo,
    not a plain directory)."""
    result = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=path)
    return result.returncode == 0 and result.stdout.strip() == "true"


class GitWorktreeIsolationManager:
    """Creates, integrates, and cleans up one dedicated git worktree per
    orchestration run, so two runs targeting the same repository
    concurrently never write to the same working tree or index."""

    def create(self, repo_root: str, run_id: str) -> IsolatedWorkspace:
        """Create a new worktree off `repo_root`'s current branch, on a
        fresh branch named `keystone/run-<sanitized run_id>`.

        Raises `WorkspaceIsolationSetupError` if `repo_root` is not a git
        working tree, `HEAD` is detached, or the worktree cannot be
        created (e.g. the branch already exists from a prior run that was
        never cleaned up).
        """
        if not is_git_repository(repo_root):
            raise WorkspaceIsolationSetupError(
                f"workspace_root '{repo_root}' is not a git working tree; "
                "isolate_workspace requires a real git repository"
            )

        branch_result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root)
        if branch_result.returncode != 0:
            raise WorkspaceIsolationSetupError(
                f"could not determine the current branch of '{repo_root}': "
                f"{branch_result.stderr.strip()[:_STDERR_LIMIT]}"
            )
        base_branch = branch_result.stdout.strip()
        if not base_branch or base_branch == "HEAD":
            raise WorkspaceIsolationSetupError(
                f"'{repo_root}' has a detached HEAD; isolate_workspace requires "
                "a real checked-out branch"
            )

        branch_name = f"keystone/run-{_safe_branch_suffix(run_id)}"
        worktree_path = tempfile.mkdtemp(prefix="keystone-worktree-")
        # `git worktree add` requires the target directory to not already
        # exist (or be empty) -- `mkdtemp` guarantees exactly that.
        add_result = _run_git(
            ["worktree", "add", "-b", branch_name, worktree_path, base_branch],
            cwd=repo_root,
        )
        if add_result.returncode != 0:
            shutil.rmtree(worktree_path, ignore_errors=True)
            raise WorkspaceIsolationSetupError(
                f"failed to create isolated worktree for run '{run_id}': "
                f"{add_result.stderr.strip()[:_STDERR_LIMIT]}"
            )

        return IsolatedWorkspace(
            repo_root=repo_root,
            worktree_path=worktree_path,
            branch_name=branch_name,
            base_branch=base_branch,
        )

    def integrate(self, workspace: IsolatedWorkspace) -> None:
        """Commit any pending changes a step left in the worktree, then
        merge `workspace`'s branch back into its base branch, inside
        `repo_root`'s own working tree (git worktrees share one object
        database/ref namespace, so this is a normal local merge).

        Real coding-agent CLIs write files but never `git commit` on their
        own, so without this the branch would still point at its starting
        commit and a "successful" merge would silently integrate nothing.

        Raises `WorkspaceIntegrationConflictError` if the pending changes
        cannot be committed, or on any merge conflict / non-zero merge
        result. The merge is aborted first, leaving `repo_root` clean; the
        run's branch (and its worktree, still holding any uncommitted
        state) is left in place -- not deleted by `cleanup` in this case --
        so the work is never silently lost.
        """
        status_result = _run_git(["status", "--porcelain"], cwd=workspace.worktree_path)
        if status_result.returncode == 0 and status_result.stdout.strip():
            add_result = _run_git(["add", "-A"], cwd=workspace.worktree_path)
            commit_result = (
                _run_git(
                    ["commit", "-m", f"keystone: work performed on {workspace.branch_name}"],
                    cwd=workspace.worktree_path,
                )
                if add_result.returncode == 0
                else add_result
            )
            if commit_result.returncode != 0:
                raise WorkspaceIntegrationConflictError(
                    f"could not commit pending changes in isolated worktree for "
                    f"'{workspace.branch_name}': {commit_result.stderr.strip()[:_STDERR_LIMIT]}. "
                    f"The worktree was left in place at '{workspace.worktree_path}' for "
                    "manual resolution."
                )

        merge_result = _run_git(
            [
                "merge",
                "--no-ff",
                "-m",
                f"merge(keystone): integrate {workspace.branch_name}",
                workspace.branch_name,
            ],
            cwd=workspace.repo_root,
        )
        if merge_result.returncode != 0:
            _run_git(["merge", "--abort"], cwd=workspace.repo_root)
            raise WorkspaceIntegrationConflictError(
                f"could not cleanly integrate '{workspace.branch_name}' into "
                f"'{workspace.base_branch}': {merge_result.stderr.strip()[:_STDERR_LIMIT]}. "
                f"The branch was left in place in '{workspace.repo_root}' for "
                "manual resolution."
            )

    def cleanup(self, workspace: IsolatedWorkspace, *, delete_branch: bool) -> None:
        """Best-effort worktree removal -- a cleanup failure is only
        logged, never raised, so it can never mask the real outcome of
        `create`/`integrate` (mirrors `app.adapters.process_runner`'s
        `_cleanup_temp_dir` discipline). `delete_branch` must be `False`
        after a failed `integrate` (the branch is that run's only
        remaining copy of the work) and should be `True` after a
        successful one.
        """
        for attempt in range(_CLEANUP_RETRY_ATTEMPTS):
            remove_result = _run_git(
                ["worktree", "remove", "--force", workspace.worktree_path],
                cwd=workspace.repo_root,
            )
            if remove_result.returncode == 0:
                break
            if attempt == _CLEANUP_RETRY_ATTEMPTS - 1:
                logger.warning(
                    "failed to remove isolated worktree after retries path=%s stderr=%s",
                    workspace.worktree_path,
                    remove_result.stderr.strip()[:_STDERR_LIMIT],
                )
            else:
                time.sleep(_CLEANUP_RETRY_BASE_DELAY_SECONDS * (attempt + 1))
        shutil.rmtree(workspace.worktree_path, ignore_errors=True)

        if delete_branch:
            branch_result = _run_git(
                ["branch", "-D", workspace.branch_name], cwd=workspace.repo_root
            )
            if branch_result.returncode != 0:
                logger.warning(
                    "failed to delete isolated run branch=%s stderr=%s",
                    workspace.branch_name,
                    branch_result.stderr.strip()[:_STDERR_LIMIT],
                )


__all__ = [
    "GitWorktreeIsolationManager",
    "IsolatedWorkspace",
    "is_git_repository",
]
