"""Provider-neutral Git worktree isolation for multi-agent task execution.

**Why this exists.** Every task in one orchestration execution previously
shared one directory (`OrchestrationRequest.workspace_root` -- the user's
real, currently-open project folder). Two agents assigned to tasks that
happen to run concurrently (`WorkflowEngine.execute_workflow_async`'s own
file-ownership-based scheduling already avoids *declared* conflicts, see
that module's docstring) could still corrupt each other's work if a task
touches a file it never declared, or simply because "no isolation" is a
fragile invariant to depend on for something as consequential as a user's
real repository. This module adds a *structural* guarantee underneath that
scheduling: each task gets its own directory that literally cannot be
written to by any other task.

**The model, in one paragraph.** `TaskWorkspaceCoordinator` treats the
user's opened folder as the canonical Git repository. For each task it
creates a `git worktree` under `<workspace>/.keystone/worktrees/<execution
id>/<task key>/`, checked out on its own throwaway branch, branched from
the current tip of a per-execution "integration candidate" branch (or the
execution's baseline commit, for the first task). Once a task's own
verification passes, its branch is merged into the candidate branch
(`integrate()`); a real conflict is never silently resolved -- the merge is
aborted, the conflicting files are reported, and the caller (`service.py`)
downgrades that task's verification to FAILED so the existing Stage 4E
recovery mechanism decides what happens next (retry, reroute, human
review), exactly as it already does for any other verification failure.
Only once the *whole* orchestration reaches `VERIFIED_SUCCESS` does
`finalize()` merge the candidate branch into whatever the user actually has
checked out in the canonical workspace -- a real `git merge`, which itself
refuses (never silently overwrites) if it would clobber the user's own
uncommitted work.

**Never a second orchestration engine.** This module owns no scheduling,
retry, or verification logic -- it only answers two questions a caller
(`WorkflowEngine`'s per-step execution and `EndToEndOrchestrationService`'s
verification resolver) already needs an answer to: "what directory does
this task run in" and "is this task's result safe to combine with
everyone else's." `WorkflowEngine`'s existing dependency-respecting
scheduling decides *when* a task runs; this module only ever changes
*where*.

**Fails safe, always.** If `workspace_root` is not (and cannot become) a
usable Git repository -- `git` missing, permission failure, anything --
`TaskWorkspaceCoordinator.enabled` is `False` and every method becomes a
transparent passthrough to the legacy, single-shared-directory behavior.
Isolation is additive: it is never the only thing standing between a task
and the canonical workspace being corrupted, because a disabled coordinator
never touches the canonical workspace at all until `finalize()`'s own
gated, git-native merge.

**Provider-neutral.** Nothing here ever branches on `agent_type` --
`workspace_for`/`integrate`/`finalize` are keyed only by `task_key`, a
Planner-assigned identifier. Whichever adapter the Router selected receives
its task's directory the same way any other adapter would.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import subprocess
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.engine.orchestration.evidence_collector import WorkspaceEvidenceCollector

logger = logging.getLogger(__name__)

_GIT_TIMEOUT_SECONDS = 30.0
_WORKTREES_DIRNAME = ".keystone/worktrees"
_EVIDENCE_DIRNAME = ".keystone/evidence"
_CANDIDATE_KEY = "_candidate"
_MAX_TRACKED_FILES = 200
_SLUG_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _slug(value: str) -> str:
    """A filesystem- and git-ref-safe identifier derived from a task key.
    Bounded and never empty -- a task key that sanitizes to nothing (or a
    path-traversal attempt) falls back to a short hash so it can never
    escape `.keystone/worktrees/<execution_id>/` or collide silently."""
    cleaned = _SLUG_RE.sub("-", value).strip("-.")
    if not cleaned or cleaned in (".", ".."):
        cleaned = f"task-{abs(hash(value)) % 100000}"
    return cleaned[:80]


def _run_git(
    args: list[str], *, cwd: str, timeout: float = _GIT_TIMEOUT_SECONDS
) -> subprocess.CompletedProcess[str]:
    """The one place this module invokes `git` -- always `shell=False`,
    always a fixed argv this module itself constructed (never derived from
    a prompt, model response, or task input), always bounded by timeout."""
    return subprocess.run(  # noqa: S603 - shell=False, argv-only, fixed internal argv
        ["git", *args],
        cwd=cwd,
        shell=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _parse_porcelain_paths(porcelain_output: str) -> list[str]:
    paths: list[str] = []
    for line in porcelain_output.splitlines():
        if len(line) > 3:
            paths.append(line[3:].strip().strip('"'))
    return sorted(set(paths))[:_MAX_TRACKED_FILES]


@dataclass(frozen=True)
class IntegrationOutcome:
    """The result of attempting to combine one task's completed work into
    the shared integration candidate. `status` is one of `"integrated"`
    (merged cleanly, possibly with zero file changes), `"conflict"`
    (aborted, nothing merged -- see `conflicting_files`), or `"skipped"`
    (isolation was not active for this task)."""

    status: str
    files_changed: tuple[str, ...] = ()
    conflicting_files: tuple[str, ...] = ()
    commit_sha: str | None = None


@dataclass(frozen=True)
class FinalizeOutcome:
    """The result of the one, final merge of the integration candidate
    into the canonical workspace, plus cleanup."""

    merged_to_canonical: bool
    conflicting_files: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class WorktreeEvent:
    """One observable fact this module recorded, queued for the caller to
    replay as a real `OrchestrationEvent` on the main event loop (this
    module's own methods may run inside `WorkflowEngine`'s worker threads
    -- see `execute_workflow_async` -- so it never emits async events
    itself; see `TaskWorkspaceCoordinator.drain_events`)."""

    event_type: str
    task_key: str | None = None
    message: str | None = None
    relative_path: str | None = None
    safe_issue_codes: tuple[str, ...] = ()
    status: str | None = None


@dataclass
class _TaskState:
    path: str
    branch: str
    collector: WorkspaceEvidenceCollector
    integrated: bool = False
    result: IntegrationOutcome | None = None


class TaskWorkspaceCoordinator:
    """Per-execution, thread-safe coordinator for task-level Git worktree
    isolation. One instance is owned by one `EndToEndOrchestrationService
    .orchestrate()` call and shared by every phase (including recovery
    cycles) of that one execution -- never across two executions, mirroring
    `WorkspaceEvidenceCollector`'s own per-attempt lifecycle discipline.

    Every public method is safe to call from multiple threads concurrently
    (`WorkflowEngine.execute_workflow_async` genuinely runs step execution
    in a thread pool via `asyncio.to_thread`) -- a single lock serializes
    all state mutation and all Git operations against the shared candidate
    worktree. Operations against two *different* task worktrees could in
    principle run in parallel, but Git itself is fast enough here (small,
    local, no network) that a single coordinator-wide lock keeps this
    module simple without being a meaningful bottleneck.
    """

    def __init__(self, canonical_workspace_root: str, execution_id: str) -> None:
        self._canonical_root = canonical_workspace_root
        self._execution_id = execution_id
        self._lock = threading.RLock()
        self._events: list[WorktreeEvent] = []
        self._tasks: dict[str, _TaskState] = {}
        self._candidate_branch = f"keystone/{execution_id}/candidate"
        self._candidate_path = str(
            Path(canonical_workspace_root) / _WORKTREES_DIRNAME / execution_id / _CANDIDATE_KEY
        )
        self._candidate_created = False
        self._worktrees_root = str(
            Path(canonical_workspace_root) / _WORKTREES_DIRNAME / execution_id
        )
        self._evidence_root = str(
            Path(canonical_workspace_root) / _EVIDENCE_DIRNAME / execution_id
        )
        self._enabled = self._detect_or_init_repo()
        self._baseline_ref = self._capture_baseline_ref() if self._enabled else None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def drain_events(self) -> list[WorktreeEvent]:
        """Return and clear every event recorded since the last drain, in
        the order they were recorded."""
        with self._lock:
            events, self._events = self._events, []
            return events

    # --- Setup ---------------------------------------------------------

    def _detect_or_init_repo(self) -> bool:
        try:
            probe = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=self._canonical_root)
        except (OSError, subprocess.SubprocessError):
            logger.info("worktree_isolation_disabled reason=git_unavailable")
            return False
        if probe.returncode == 0 and probe.stdout.strip() == "true":
            return self._ensure_has_commit()
        try:
            init_result = _run_git(["init"], cwd=self._canonical_root)
            if init_result.returncode != 0:
                logger.warning("worktree_isolation_disabled reason=git_init_failed")
                return False
        except (OSError, subprocess.SubprocessError):
            logger.warning("worktree_isolation_disabled reason=git_init_error")
            return False
        logger.info("worktree_isolation_git_initialized workspace_root=%s", self._canonical_root)
        return self._ensure_has_commit()

    def _ensure_has_commit(self) -> bool:
        try:
            verify = _run_git(["rev-parse", "--verify", "HEAD"], cwd=self._canonical_root)
            if verify.returncode == 0:
                return True
            _run_git(["add", "-A"], cwd=self._canonical_root)
            commit = _run_git(
                [
                    "-c",
                    "user.email=keystone@localhost",
                    "-c",
                    "user.name=Keystone",
                    "commit",
                    "--allow-empty",
                    "-m",
                    "Keystone: baseline snapshot before isolated multi-agent execution",
                ],
                cwd=self._canonical_root,
            )
            return commit.returncode == 0
        except (OSError, subprocess.SubprocessError):
            logger.warning("worktree_isolation_disabled reason=baseline_commit_failed")
            return False

    def _capture_baseline_ref(self) -> str:
        """The task-worktree starting point: the working tree's current
        state, uncommitted changes to *tracked* files included, captured
        without touching HEAD or the working directory (`git stash
        create` builds a commit object; it never stashes/pops anything).
        Newly created, not-yet-tracked files are not captured this way --
        a documented scope boundary, not a silent gap: capturing those
        losslessly would require mutating the user's real working tree
        (`git stash push -u`), which this module deliberately never risks.
        Falls back to `HEAD` when the tree is already clean or `git stash
        create` cannot run for any reason."""
        try:
            result = _run_git(["stash", "create"], cwd=self._canonical_root)
            sha = result.stdout.strip()
            if result.returncode == 0 and sha:
                return sha
        except (OSError, subprocess.SubprocessError):
            pass
        return "HEAD"

    # --- Per-task worktree lifecycle ------------------------------------

    def workspace_for(self, task_key: str) -> str:
        """Returns the directory this task's execution must run in.
        Idempotent within one attempt; creates a fresh worktree (evicting
        a prior one) if this `task_key` already reached a terminal
        integration outcome -- i.e. this call is a recovery re-attempt,
        not a within-attempt retry."""
        if not self._enabled:
            return self._canonical_root
        with self._lock:
            existing = self._tasks.get(task_key)
            if existing is not None and not existing.integrated:
                return existing.path
            if existing is not None and existing.integrated:
                self._evict_task_locked(task_key)

            slug = _slug(task_key)
            path = str(Path(self._worktrees_root) / slug)
            branch = f"keystone/{self._execution_id}/{slug}"
            base_ref = self._candidate_branch if self._candidate_created else self._baseline_ref
            assert base_ref is not None  # guarded by `self._enabled`

            if not self._create_worktree(path, branch, base_ref):
                self._record_event(
                    "workspace.created",
                    task_key=task_key,
                    message="isolated worktree creation failed; falling back to shared workspace",
                    status="failed",
                )
                return self._canonical_root

            self._tasks[task_key] = _TaskState(
                path=path, branch=branch, collector=WorkspaceEvidenceCollector(path)
            )
            self._record_event(
                "workspace.created",
                task_key=task_key,
                relative_path=str(Path(_WORKTREES_DIRNAME) / self._execution_id / slug),
                message=f"isolated worktree ready for task '{task_key}'",
                status="created",
            )
            return path

    def collector_for(self, task_key: str) -> WorkspaceEvidenceCollector | None:
        with self._lock:
            state = self._tasks.get(task_key)
            return state.collector if state is not None else None

    def _create_worktree(self, path: str, branch: str, base_ref: str) -> bool:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        try:
            result = _run_git(
                ["worktree", "add", "-b", branch, path, base_ref], cwd=self._canonical_root
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("worktree_create_failed task_branch=%s error=%s", branch, exc)
            return False
        if result.returncode != 0:
            logger.warning(
                "worktree_create_failed task_branch=%s stderr=%s", branch, result.stderr[:500]
            )
            return False
        return True

    def _evict_task_locked(self, task_key: str) -> None:
        state = self._tasks.pop(task_key, None)
        if state is None:
            return
        self._remove_worktree_locked(state.path)
        _run_git(["branch", "-D", state.branch], cwd=self._canonical_root)

    # --- Integration -----------------------------------------------------

    def integrate(self, task_key: str) -> IntegrationOutcome:
        """Commits a succeeded task's changes and merges them into the
        shared integration candidate. Never overwrites: a real merge
        conflict aborts cleanly and is reported, never resolved silently.
        Idempotent -- calling twice for the same task_key without an
        intervening `workspace_for` re-creation returns the cached result."""
        if not self._enabled:
            return IntegrationOutcome(status="skipped")
        with self._lock:
            state = self._tasks.get(task_key)
            if state is None:
                return IntegrationOutcome(status="skipped")
            if state.integrated and state.result is not None:
                return state.result

            files_changed = self._commit_pending_changes_locked(state)
            commit_sha = self._rev_parse_locked(state.path, "HEAD")

            self._record_event(
                "integration.started",
                task_key=task_key,
                message=f"integrating {len(files_changed)} file(s) from '{task_key}'",
            )
            self._ensure_candidate_worktree_locked()
            merge_result = _run_git(
                ["merge", "--no-ff", "-m", f"Keystone: integrate task '{task_key}'", state.branch],
                cwd=self._candidate_path,
            )
            if merge_result.returncode != 0:
                conflicts = self._conflicting_files_locked(self._candidate_path)
                _run_git(["merge", "--abort"], cwd=self._candidate_path)
                outcome = IntegrationOutcome(status="conflict", conflicting_files=tuple(conflicts))
                self._record_event(
                    "integration.conflict",
                    task_key=task_key,
                    safe_issue_codes=tuple(conflicts),
                    message=f"integration conflict on {len(conflicts)} file(s) for '{task_key}'",
                    status="conflict",
                )
            else:
                outcome = IntegrationOutcome(
                    status="integrated", files_changed=tuple(files_changed), commit_sha=commit_sha
                )
                self._record_event(
                    "integration.completed",
                    task_key=task_key,
                    message=f"{len(files_changed)} file(s) integrated from '{task_key}'",
                    status="integrated",
                )

            state.integrated = True
            state.result = outcome
            self._persist_evidence_locked(task_key, outcome)
            return outcome

    def _commit_pending_changes_locked(self, state: _TaskState) -> list[str]:
        _run_git(["add", "-A"], cwd=state.path)
        status = _run_git(["status", "--porcelain"], cwd=state.path)
        changed = _parse_porcelain_paths(status.stdout)
        if changed:
            _run_git(
                [
                    "-c",
                    "user.email=keystone@localhost",
                    "-c",
                    "user.name=Keystone",
                    "commit",
                    "-m",
                    f"Keystone: task '{state.branch}' changes",
                ],
                cwd=state.path,
            )
        return changed

    def _rev_parse_locked(self, cwd: str, ref: str) -> str | None:
        result = _run_git(["rev-parse", ref], cwd=cwd)
        return result.stdout.strip() if result.returncode == 0 else None

    def _ensure_candidate_worktree_locked(self) -> None:
        if self._candidate_created:
            return
        assert self._baseline_ref is not None
        created = self._create_worktree(
            self._candidate_path, self._candidate_branch, self._baseline_ref
        )
        self._candidate_created = created

    def _conflicting_files_locked(self, worktree_path: str) -> list[str]:
        result = _run_git(["diff", "--name-only", "--diff-filter=U"], cwd=worktree_path)
        if result.returncode != 0:
            return []
        return sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})[
            :_MAX_TRACKED_FILES
        ]

    def _persist_evidence_locked(self, task_key: str, outcome: IntegrationOutcome) -> None:
        try:
            Path(self._evidence_root).mkdir(parents=True, exist_ok=True)
            evidence_path = Path(self._evidence_root) / f"{_slug(task_key)}.json"
            evidence_path.write_text(
                json.dumps(
                    {
                        "task_key": task_key,
                        "status": outcome.status,
                        "files_changed": list(outcome.files_changed),
                        "conflicting_files": list(outcome.conflicting_files),
                        "commit_sha": outcome.commit_sha,
                        "recorded_at": datetime.now(UTC).isoformat(),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            logger.warning("worktree_evidence_persist_failed task_key=%s", task_key)

    # --- Finalization ------------------------------------------------------

    def finalize(self, *, succeeded: bool) -> FinalizeOutcome:
        """Merges the integration candidate into the canonical workspace
        (only when `succeeded`), then removes every worktree this
        coordinator created -- always, regardless of outcome. Evidence
        (`.keystone/evidence/<execution_id>/*.json`) is never deleted."""
        if not self._enabled:
            return FinalizeOutcome(merged_to_canonical=False)
        with self._lock:
            outcome = FinalizeOutcome(merged_to_canonical=False)
            if succeeded and self._candidate_created:
                merge_result = _run_git(
                    [
                        "merge",
                        "--no-ff",
                        "-m",
                        f"Keystone: integrate execution {self._execution_id}",
                        self._candidate_branch,
                    ],
                    cwd=self._canonical_root,
                )
                if merge_result.returncode == 0:
                    outcome = FinalizeOutcome(merged_to_canonical=True)
                    self._record_event(
                        "integration.completed",
                        message="final result merged into the canonical workspace",
                        status="merged",
                    )
                else:
                    conflicts = self._conflicting_files_locked(self._canonical_root)
                    _run_git(["merge", "--abort"], cwd=self._canonical_root)
                    outcome = FinalizeOutcome(
                        merged_to_canonical=False,
                        conflicting_files=tuple(conflicts),
                        error="final integration conflicted with the canonical workspace's "
                        "own local state; the canonical workspace was left untouched",
                    )
                    self._record_event(
                        "integration.conflict",
                        safe_issue_codes=tuple(conflicts),
                        message="final integration conflicted; canonical workspace untouched",
                        status="conflict",
                    )

            self._cleanup_worktrees_locked()
            return outcome

    def _cleanup_worktrees_locked(self) -> None:
        import shutil

        for state in list(self._tasks.values()):
            self._remove_worktree_locked(state.path)
        if self._candidate_created:
            self._remove_worktree_locked(self._candidate_path)
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            _run_git(["worktree", "prune"], cwd=self._canonical_root)
        # `git worktree remove` only ever removes one worktree directory,
        # never this execution's now-empty container
        # (`.keystone/worktrees/<execution_id>/`) -- remove that too, but
        # only that exact, entirely Keystone-owned directory, never
        # anything above it.
        canonical = Path(self._canonical_root).resolve()
        worktrees_root = Path(self._worktrees_root).resolve()
        if worktrees_root.exists() and canonical in worktrees_root.parents:
            shutil.rmtree(worktrees_root, ignore_errors=True)

    def _remove_worktree_locked(self, path: str) -> None:
        try:
            _run_git(["worktree", "remove", "--force", path], cwd=self._canonical_root)
        except (OSError, subprocess.SubprocessError):
            logger.warning("worktree_remove_failed path=%s", path)
        # Belt-and-suspenders: `git worktree remove` already deletes the
        # directory on success; this only ever touches paths under this
        # execution's own `.keystone/worktrees/<execution_id>/` tree --
        # never anything else in the canonical workspace.
        if Path(path).exists() and Path(self._worktrees_root) in Path(path).resolve().parents:
            import shutil

            shutil.rmtree(path, ignore_errors=True)

    # --- Internal ---------------------------------------------------------

    def _record_event(self, event_type: str, **fields: object) -> None:
        self._events.append(WorktreeEvent(event_type=event_type, **fields))  # type: ignore[arg-type]


__all__ = [
    "FinalizeOutcome",
    "IntegrationOutcome",
    "TaskWorkspaceCoordinator",
    "WorktreeEvent",
]
