"""Unit tests for `GitWorktreeIsolationManager`
(`app.engine.orchestration.workspace_isolation`) against real, temporary git
repositories -- no mocked git, since the whole point of this module is that
the isolation it provides is real."""

import subprocess
from pathlib import Path

import pytest

from app.engine.orchestration.errors import (
    WorkspaceIntegrationConflictError,
    WorkspaceIsolationSetupError,
)
from app.engine.orchestration.workspace_isolation import (
    GitWorktreeIsolationManager,
    is_git_repository,
)


def _git(args: list[str], *, cwd: Path) -> None:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30, shell=False
    )
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"


def _init_repo(path: Path) -> None:
    _git(["init", "-b", "main"], cwd=path)
    _git(["config", "user.email", "test@example.com"], cwd=path)
    _git(["config", "user.name", "Keystone Test"], cwd=path)
    (path / "README.md").write_text("initial\n", encoding="utf-8")
    _git(["add", "README.md"], cwd=path)
    _git(["commit", "-m", "initial commit"], cwd=path)


def test_is_git_repository_true_for_real_repo(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    assert is_git_repository(str(tmp_path)) is True


def test_is_git_repository_false_for_plain_directory(tmp_path: Path) -> None:
    assert is_git_repository(str(tmp_path)) is False


def test_is_git_repository_false_for_nonexistent_path(tmp_path: Path) -> None:
    assert is_git_repository(str(tmp_path / "does-not-exist")) is False


def test_create_rejects_non_git_workspace_root(tmp_path: Path) -> None:
    manager = GitWorktreeIsolationManager()
    with pytest.raises(WorkspaceIsolationSetupError):
        manager.create(str(tmp_path), "run-1")


def test_create_then_integrate_merges_real_file_back(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    manager = GitWorktreeIsolationManager()

    workspace = manager.create(str(tmp_path), "req id with spaces:1")
    assert workspace.base_branch == "main"
    assert Path(workspace.worktree_path).is_dir()
    assert workspace.worktree_path != str(tmp_path)

    (Path(workspace.worktree_path) / "new_file.txt").write_text("hello\n", encoding="utf-8")
    _git(["add", "new_file.txt"], cwd=Path(workspace.worktree_path))
    _git(["commit", "-m", "add new_file.txt"], cwd=Path(workspace.worktree_path))

    # Not yet integrated: the original checkout must not see the new file.
    assert not (tmp_path / "new_file.txt").exists()

    manager.integrate(workspace)
    assert (tmp_path / "new_file.txt").read_text(encoding="utf-8") == "hello\n"

    manager.cleanup(workspace, delete_branch=True)
    worktree_list = subprocess.run(
        ["git", "worktree", "list"], cwd=tmp_path, capture_output=True, text=True, timeout=30
    ).stdout
    assert workspace.worktree_path not in worktree_list
    branch_list = subprocess.run(
        ["git", "branch", "--list", workspace.branch_name],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout
    assert workspace.branch_name not in branch_list


def test_conflicting_integrate_raises_and_preserves_the_branch(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "shared.txt").write_text("original\n", encoding="utf-8")
    _git(["add", "shared.txt"], cwd=tmp_path)
    _git(["commit", "-m", "add shared.txt"], cwd=tmp_path)

    manager = GitWorktreeIsolationManager()
    workspace = manager.create(str(tmp_path), "conflict-run")

    (Path(workspace.worktree_path) / "shared.txt").write_text(
        "changed-in-worktree\n", encoding="utf-8"
    )
    _git(["add", "shared.txt"], cwd=Path(workspace.worktree_path))
    _git(["commit", "-m", "change shared.txt in worktree"], cwd=Path(workspace.worktree_path))

    # A conflicting change lands on the base branch in the meantime.
    (tmp_path / "shared.txt").write_text("changed-on-main\n", encoding="utf-8")
    _git(["add", "shared.txt"], cwd=tmp_path)
    _git(["commit", "-m", "change shared.txt on main"], cwd=tmp_path)

    with pytest.raises(WorkspaceIntegrationConflictError):
        manager.integrate(workspace)

    # The base checkout must be left clean (merge aborted), not mid-conflict.
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=tmp_path, capture_output=True, text=True, timeout=30
    ).stdout
    assert status.strip() == ""
    assert (tmp_path / "shared.txt").read_text(encoding="utf-8") == "changed-on-main\n"

    # Cleanup after a failed integrate must never delete the branch -- it's
    # the only remaining copy of that run's work.
    manager.cleanup(workspace, delete_branch=False)
    branch_list = subprocess.run(
        ["git", "branch", "--list", workspace.branch_name],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout
    assert workspace.branch_name in branch_list


def test_branch_name_sanitizes_unsafe_request_id_characters(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    manager = GitWorktreeIsolationManager()
    workspace = manager.create(str(tmp_path), "req/with weird:chars*?")
    assert workspace.branch_name.startswith("keystone/run-")
    for unsafe in (" ", ":", "*", "?"):
        assert unsafe not in workspace.branch_name
    manager.cleanup(workspace, delete_branch=True)
