"""Task Worktree Isolation -- proves `TaskWorkspaceCoordinator`
(`app.engine.orchestration.worktree`) gives concurrently-executing tasks
genuinely separate directories, integrates non-conflicting work
deterministically, never silently overwrites a real conflict, never
corrupts the canonical workspace with a failed or unintegrated task's
changes, and cleans up after itself without ever touching a real user
file.

Direct, fast, fully-controlled tests against the coordinator itself (this
file) cover the isolation/integration/conflict/cleanup matrix; one
end-to-end test through the real `EndToEndOrchestrationService.orchestrate()`
pipeline (mirroring `test_orchestration_workspace_evidence.py`'s own
`WorkspaceWritingExecutor` pattern) proves the production wiring -- per-task
worktree, real git integration, final merge into the canonical workspace,
and cleanup -- actually fires end to end, not just in isolation.
"""

import inspect
import subprocess
from pathlib import Path

from sqlalchemy.orm import Session

from app.engine.orchestration import worktree as worktree_module
from app.engine.orchestration.models import OrchestrationOutcome
from app.engine.orchestration.worktree import TaskWorkspaceCoordinator
from tests.test_orchestration_workspace_evidence import WorkspaceWritingExecutor, _request, _service


def _seed_repo(root: Path, **files: str) -> None:
    for name, content in files.items():
        (root / name).write_text(content, encoding="utf-8")


def _write_files(root: Path, **files: str) -> None:
    """Writes files (creating parent directories) without touching git at
    all -- used to create genuinely *untracked* content after a repo
    already has a baseline commit, mirroring a real user who edited/added
    files and then immediately submitted a goal without committing."""
    for relative_name, content in files.items():
        path = root / relative_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _init_git_baseline(root: Path, **files: str) -> None:
    """Establishes a real, already-committed repo -- the state
    `TaskWorkspaceCoordinator` itself would find if it never had to
    auto-`git init` anything. Files passed here become *tracked*; anything
    written afterward via `_write_files` stays genuinely untracked."""
    _write_files(root, **files)
    env = ["-c", "user.email=test@localhost", "-c", "user.name=Test"]
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", *env, "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", *env, "commit", "-m", "baseline"], cwd=root, check=True, capture_output=True
    )


def _coordinator(root: Path, execution_id: str = "exec-1") -> TaskWorkspaceCoordinator:
    return TaskWorkspaceCoordinator(str(root), execution_id)


# --- Setup / provider neutrality ---------------------------------------


def test_auto_initializes_git_and_enables_isolation_for_a_plain_folder(tmp_path: Path) -> None:
    _seed_repo(tmp_path, **{"README.md": "hello\n"})
    coord = _coordinator(tmp_path)
    assert coord.enabled is True
    assert not (tmp_path / ".keystone").exists()  # nothing created until a task is assigned


def test_disabled_gracefully_when_git_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    def _raise(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(worktree_module.subprocess, "run", _raise)
    coord = _coordinator(tmp_path)

    assert coord.enabled is False
    # A disabled coordinator transparently falls back to the canonical
    # directory for every task -- legacy, single-shared-workspace behavior.
    assert coord.workspace_for("task-a") == str(tmp_path)
    assert coord.integrate("task-a").status == "skipped"
    assert coord.finalize(succeeded=True).merged_to_canonical is False


def test_public_surface_never_mentions_a_specific_provider(tmp_path: Path) -> None:
    """Isolation is keyed only by `task_key` -- structurally verified by
    the module never naming a specific agent/provider anywhere in it."""
    source = inspect.getsource(worktree_module)
    for forbidden in ("claude", "codex", "antigravity", "gemini"):
        assert forbidden not in source.lower(), (
            f"worktree.py must stay provider-neutral: found {forbidden!r}"
        )


# --- Isolation ------------------------------------------------------------


def test_two_tasks_receive_different_working_directories(tmp_path: Path) -> None:
    _seed_repo(tmp_path, **{"README.md": "hello\n"})
    coord = _coordinator(tmp_path)

    path_a = coord.workspace_for("build-backend")
    path_b = coord.workspace_for("build-frontend")

    assert path_a != path_b
    assert Path(path_a).is_dir()
    assert Path(path_b).is_dir()
    assert Path(path_a).resolve() != tmp_path.resolve()
    assert Path(path_b).resolve() != tmp_path.resolve()


def test_similarly_named_files_never_corrupt_each_others_worktree(tmp_path: Path) -> None:
    _seed_repo(tmp_path, **{"README.md": "hello\n"})
    coord = _coordinator(tmp_path)

    path_a = Path(coord.workspace_for("agent-one-task"))
    path_b = Path(coord.workspace_for("agent-two-task"))
    (path_a / "output.py").write_text("value = 'from A'\n", encoding="utf-8")
    (path_b / "output.py").write_text("value = 'from B'\n", encoding="utf-8")

    assert (path_a / "output.py").read_text(encoding="utf-8") == "value = 'from A'\n"
    assert (path_b / "output.py").read_text(encoding="utf-8") == "value = 'from B'\n"


# --- Integration ------------------------------------------------------------


def test_non_conflicting_changes_integrate_and_reach_canonical_workspace(tmp_path: Path) -> None:
    _seed_repo(tmp_path, **{"README.md": "hello\n"})
    coord = _coordinator(tmp_path)

    a = Path(coord.workspace_for("backend-task"))
    b = Path(coord.workspace_for("frontend-task"))
    (a / "backend.py").write_text("# backend\n", encoding="utf-8")
    (b / "frontend.ts").write_text("// frontend\n", encoding="utf-8")

    outcome_a = coord.integrate("backend-task")
    outcome_b = coord.integrate("frontend-task")
    assert outcome_a.status == "integrated"
    assert outcome_b.status == "integrated"
    assert "backend.py" in outcome_a.files_changed
    assert "frontend.ts" in outcome_b.files_changed

    final = coord.finalize(succeeded=True)
    assert final.merged_to_canonical is True
    assert (tmp_path / "backend.py").read_text(encoding="utf-8") == "# backend\n"
    assert (tmp_path / "frontend.ts").read_text(encoding="utf-8") == "// frontend\n"


def test_dependent_task_sees_already_integrated_predecessor_output(tmp_path: Path) -> None:
    _seed_repo(tmp_path, **{"README.md": "hello\n"})
    coord = _coordinator(tmp_path)

    upstream = Path(coord.workspace_for("define-schema"))
    (upstream / "schema.py").write_text("SCHEMA = {}\n", encoding="utf-8")
    outcome = coord.integrate("define-schema")
    assert outcome.status == "integrated"

    # A task requested *after* its dependency was integrated (exactly how
    # `WorkflowEngine`'s dependency-respecting scheduling calls
    # `workspace_for`) starts from a worktree that already contains it.
    downstream = Path(coord.workspace_for("use-schema"))
    assert (downstream / "schema.py").exists()
    assert (downstream / "schema.py").read_text(encoding="utf-8") == "SCHEMA = {}\n"


# --- Conflicts, never silently resolved ------------------------------------


def test_conflicting_changes_are_reported_and_canonical_stays_untouched(tmp_path: Path) -> None:
    _seed_repo(tmp_path, **{"shared.py": "value = 'base'\n"})
    coord = _coordinator(tmp_path)

    a = Path(coord.workspace_for("agent-a-task"))
    b = Path(coord.workspace_for("agent-b-task"))
    (a / "shared.py").write_text("value = 'from A'\n", encoding="utf-8")
    (b / "shared.py").write_text("value = 'from B'\n", encoding="utf-8")

    outcome_a = coord.integrate("agent-a-task")
    assert outcome_a.status == "integrated"

    outcome_b = coord.integrate("agent-b-task")
    assert outcome_b.status == "conflict"
    assert "shared.py" in outcome_b.conflicting_files

    # The conflict never touched the canonical workspace -- it still has
    # its original content, not A's, not B's, not a mangled merge marker.
    assert (tmp_path / "shared.py").read_text(encoding="utf-8") == "value = 'base'\n"


def test_final_merge_conflict_with_canonical_leaves_canonical_untouched(tmp_path: Path) -> None:
    _seed_repo(tmp_path, **{"shared.py": "value = 'base'\n"})
    coord = _coordinator(tmp_path)

    a = Path(coord.workspace_for("agent-a-task"))
    (a / "shared.py").write_text("value = 'from A'\n", encoding="utf-8")
    assert coord.integrate("agent-a-task").status == "integrated"

    # The user keeps editing the *canonical* workspace directly while the
    # execution is in flight -- a real, conflicting concurrent edit.
    (tmp_path / "shared.py").write_text("value = 'user edit'\n", encoding="utf-8")

    final = coord.finalize(succeeded=True)
    assert final.merged_to_canonical is False
    assert (tmp_path / "shared.py").read_text(encoding="utf-8") == "value = 'user edit'\n"


# --- Failure isolation -------------------------------------------------------


def test_failed_tasks_worktree_never_integrated_or_reflected_in_canonical(
    tmp_path: Path,
) -> None:
    _seed_repo(tmp_path, **{"README.md": "hello\n"})
    coord = _coordinator(tmp_path)

    good = Path(coord.workspace_for("good-task"))
    bad = Path(coord.workspace_for("bad-task"))
    (good / "good.py").write_text("# ok\n", encoding="utf-8")
    (bad / "bad.py").write_text("# should never appear\n", encoding="utf-8")

    # Only the succeeded task is ever offered for integration -- "bad-task"
    # never calls `integrate()`, exactly as the real verification resolver
    # never does for a step whose execution/verification failed.
    coord.integrate("good-task")

    final = coord.finalize(succeeded=True)
    assert final.merged_to_canonical is True
    assert (tmp_path / "good.py").exists()
    assert not (tmp_path / "bad.py").exists()


def test_finalize_on_overall_failure_never_touches_canonical_workspace(tmp_path: Path) -> None:
    _seed_repo(tmp_path, **{"README.md": "hello\n"})
    coord = _coordinator(tmp_path)

    a = Path(coord.workspace_for("some-task"))
    (a / "wip.py").write_text("# work in progress\n", encoding="utf-8")
    coord.integrate("some-task")

    final = coord.finalize(succeeded=False)
    assert final.merged_to_canonical is False
    assert not (tmp_path / "wip.py").exists()


# --- Cleanup -----------------------------------------------------------------


def test_cleanup_removes_worktrees_but_never_deletes_real_user_files(tmp_path: Path) -> None:
    _seed_repo(tmp_path, **{"keep_me.txt": "precious user data\n"})
    coord = _coordinator(tmp_path)

    a = Path(coord.workspace_for("some-task"))
    (a / "new_file.py").write_text("# new\n", encoding="utf-8")
    coord.integrate("some-task")
    coord.finalize(succeeded=True)

    assert (tmp_path / "keep_me.txt").read_text(encoding="utf-8") == "precious user data\n"
    assert not (tmp_path / ".keystone" / "worktrees" / "exec-1").exists()
    # Evidence survives cleanup of the worktrees themselves.
    assert (tmp_path / ".keystone" / "evidence" / "exec-1" / "some-task.json").exists()


# --- Untracked files, captured at orchestration start ----------------------


def test_untracked_source_file_is_visible_to_agent(tmp_path: Path) -> None:
    _init_git_baseline(tmp_path, **{"README.md": "hello\n"})
    _write_files(tmp_path, **{"new_module.py": "def new():\n    pass\n"})

    coord = _coordinator(tmp_path)
    worktree = Path(coord.workspace_for("some-task"))

    assert (worktree / "new_module.py").exists()
    assert (worktree / "new_module.py").read_text(encoding="utf-8") == "def new():\n    pass\n"


def test_gitignored_untracked_file_is_not_copied(tmp_path: Path) -> None:
    _init_git_baseline(tmp_path, **{"README.md": "hello\n", ".gitignore": "*.local\n"})
    _write_files(tmp_path, **{"scratch.local": "not for agents\n"})

    coord = _coordinator(tmp_path)
    worktree = Path(coord.workspace_for("some-task"))

    assert not (worktree / "scratch.local").exists()


def test_secret_filename_never_copied_even_without_gitignore(tmp_path: Path) -> None:
    """`.gitignore` compliance is the primary defense (previous test); this
    proves the hardcoded denylist still protects a project whose
    `.gitignore` simply doesn't mention `.env`."""
    _init_git_baseline(tmp_path, **{"README.md": "hello\n"})
    _write_files(tmp_path, **{".env": "SECRET_TOKEN=abc123\n"})

    coord = _coordinator(tmp_path)
    worktree = Path(coord.workspace_for("some-task"))

    assert not (worktree / ".env").exists()


def test_nested_untracked_files_preserve_directory_structure(tmp_path: Path) -> None:
    _init_git_baseline(tmp_path, **{"README.md": "hello\n"})
    _write_files(tmp_path, **{"src/pkg/nested_module.py": "VALUE = 1\n"})

    coord = _coordinator(tmp_path)
    worktree = Path(coord.workspace_for("some-task"))
    nested = worktree / "src" / "pkg" / "nested_module.py"

    assert nested.exists()
    assert nested.read_text(encoding="utf-8") == "VALUE = 1\n"


def test_no_git_or_keystone_directory_recursion(tmp_path: Path) -> None:
    _init_git_baseline(tmp_path, **{"README.md": "hello\n"})
    _write_files(
        tmp_path,
        **{
            "node_modules/pkg/index.js": "module.exports = {};\n",
            ".keystone/evidence/old-exec/leftover.json": "{}\n",
        },
    )

    coord = _coordinator(tmp_path)
    worktree = Path(coord.workspace_for("some-task"))

    assert not (worktree / "node_modules").exists()
    assert not (worktree / ".keystone").exists()


def test_failed_task_with_untracked_file_preserves_canonical_original(tmp_path: Path) -> None:
    _init_git_baseline(tmp_path, **{"README.md": "hello\n"})
    _write_files(tmp_path, **{"draft.py": "original\n"})

    coord = _coordinator(tmp_path)
    worktree = Path(coord.workspace_for("failing-task"))
    (worktree / "draft.py").write_text("agent broke it\n", encoding="utf-8")
    # "failing-task" never reaches `integrate()` -- exactly what a real
    # execution/verification failure looks like from this coordinator's
    # point of view (the resolver only calls `integrate()` for a step
    # whose own attempt succeeded).

    final = coord.finalize(succeeded=True)

    assert final.merged_to_canonical is False  # nothing was ever integrated
    assert (tmp_path / "draft.py").read_text(encoding="utf-8") == "original\n"


def test_successful_modification_of_untracked_file_integrates_to_canonical(tmp_path: Path) -> None:
    _init_git_baseline(tmp_path, **{"README.md": "hello\n"})
    _write_files(tmp_path, **{"draft.py": "original\n"})

    coord = _coordinator(tmp_path)
    worktree = Path(coord.workspace_for("good-task"))
    (worktree / "draft.py").write_text("agent improved it\n", encoding="utf-8")

    outcome = coord.integrate("good-task")
    assert outcome.status == "integrated"
    assert "draft.py" in outcome.files_changed

    final = coord.finalize(succeeded=True)
    assert final.merged_to_canonical is True
    assert (tmp_path / "draft.py").read_text(encoding="utf-8") == "agent improved it\n"


def test_untouched_untracked_file_round_trips_without_blocking_integration(tmp_path: Path) -> None:
    """A copied untracked file no task ever modifies must never block the
    final merge -- its content in the integrated candidate is
    byte-identical to what canonical already has, so there is nothing for
    `git merge` to actually overwrite."""
    _init_git_baseline(tmp_path, **{"README.md": "hello\n"})
    _write_files(tmp_path, **{"context.txt": "reference material\n"})

    coord = _coordinator(tmp_path)
    worktree = Path(coord.workspace_for("some-task"))
    (worktree / "new_output.py").write_text("# real change\n", encoding="utf-8")
    # "context.txt" was copied in as agent context but never modified.

    assert coord.integrate("some-task").status == "integrated"
    final = coord.finalize(succeeded=True)

    assert final.merged_to_canonical is True
    assert (tmp_path / "context.txt").read_text(encoding="utf-8") == "reference material\n"
    assert (tmp_path / "new_output.py").exists()


def test_concurrent_tasks_get_independent_copies_of_untracked_files(tmp_path: Path) -> None:
    _init_git_baseline(tmp_path, **{"README.md": "hello\n"})
    _write_files(tmp_path, **{"shared_context.py": "base\n"})

    coord = _coordinator(tmp_path)
    a = Path(coord.workspace_for("agent-a-task"))
    b = Path(coord.workspace_for("agent-b-task"))

    assert (a / "shared_context.py").read_text(encoding="utf-8") == "base\n"
    assert (b / "shared_context.py").read_text(encoding="utf-8") == "base\n"

    (a / "shared_context.py").write_text("edited by A\n", encoding="utf-8")
    (b / "shared_context.py").write_text("edited by B\n", encoding="utf-8")

    # Two independent filesystem copies -- editing one never touches the
    # other's, and canonical is untouched by either in-flight edit.
    assert (a / "shared_context.py").read_text(encoding="utf-8") == "edited by A\n"
    assert (b / "shared_context.py").read_text(encoding="utf-8") == "edited by B\n"
    assert (tmp_path / "shared_context.py").read_text(encoding="utf-8") == "base\n"


def test_canonical_workspace_is_never_git_added_by_untracked_file_capture(tmp_path: Path) -> None:
    """Requirement: capturing/copying untracked files must never mutate or
    `git add` the canonical workspace itself."""
    _init_git_baseline(tmp_path, **{"README.md": "hello\n"})
    _write_files(tmp_path, **{"still_untracked.py": "x = 1\n"})

    coord = _coordinator(tmp_path)
    coord.workspace_for("some-task")

    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=tmp_path, check=True, capture_output=True, text=True
    )
    assert "still_untracked.py" in status.stdout
    assert status.stdout.strip().startswith("??")  # still untracked, never staged


# --- End-to-end wiring through the real orchestration pipeline --------------


async def test_end_to_end_orchestration_merges_into_canonical_workspace_and_cleans_up(
    db_session: Session, tmp_path: Path
) -> None:
    executor = WorkspaceWritingExecutor(passing=True)
    service = _service(db_session, executor=executor, enable_worktree_isolation=True)

    result = await service.orchestrate(_request(str(tmp_path)))

    assert result.outcome == OrchestrationOutcome.VERIFIED_SUCCESS
    # The real files landed in the canonical, user-opened workspace --
    # never left behind in a `.keystone/worktrees/...` subdirectory.
    assert (tmp_path / "add.js").exists()
    assert (tmp_path / "add.test.js").exists()
    assert not (tmp_path / ".keystone" / "worktrees" / result.request_id).exists()


async def test_end_to_end_orchestration_events_include_workspace_and_integration(
    db_session: Session, tmp_path: Path
) -> None:
    from app.engine.orchestration.events import OrchestrationEvent, OrchestrationEventType

    class _CollectingSink:
        def __init__(self) -> None:
            self.events: list[OrchestrationEvent] = []

        async def on_event(self, event: OrchestrationEvent) -> None:
            self.events.append(event)

    sink = _CollectingSink()
    executor = WorkspaceWritingExecutor(passing=True)
    service = _service(
        db_session, executor=executor, enable_worktree_isolation=True, event_sink=sink
    )

    result = await service.orchestrate(_request(str(tmp_path)))

    assert result.outcome == OrchestrationOutcome.VERIFIED_SUCCESS
    event_types = {event.event_type for event in sink.events}
    assert OrchestrationEventType.WORKSPACE_CREATED in event_types
    assert OrchestrationEventType.INTEGRATION_COMPLETED in event_types
