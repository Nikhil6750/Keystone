"""Unit tests for WorkspaceWatcher (Live Workspace File Activity Monitor)."""

from pathlib import Path

from app.services.workspace_watcher import WorkspaceWatcher


def test_workspace_watcher_detects_creation_modification_and_deletion(tmp_path: Path) -> None:
    watcher = WorkspaceWatcher(tmp_path)
    watcher.set_active_context(task_id="T1", agent_id="codex")

    # Initial empty snapshot
    events0 = watcher.poll_now()
    assert len(events0) == 0

    # 1. Create file
    test_file = tmp_path / "script.js"
    test_file.write_text("console.log('hello');", encoding="utf-8")

    events1 = watcher.poll_now()
    assert len(events1) == 1
    assert events1[0].relative_path == "script.js"
    assert events1[0].activity == "created"
    assert events1[0].task_id == "T1"
    assert events1[0].agent_id == "codex"

    # 2. Modify file
    test_file.write_text("console.log('updated');", encoding="utf-8")
    # Touch mtime to ensure stat change
    mtime = test_file.stat().st_mtime + 2.0
    import os
    os.utime(str(test_file), (mtime, mtime))

    events2 = watcher.poll_now()
    assert len(events2) == 1
    assert events2[0].relative_path == "script.js"
    assert events2[0].activity == "modified"

    # 3. Delete file
    test_file.unlink()

    events3 = watcher.poll_now()
    assert len(events3) == 1
    assert events3[0].relative_path == "script.js"
    assert events3[0].activity == "deleted"


def test_workspace_watcher_ignores_excluded_directories(tmp_path: Path) -> None:
    watcher = WorkspaceWatcher(tmp_path)

    node_modules = tmp_path / "node_modules" / "express"
    node_modules.mkdir(parents=True)
    (node_modules / "index.js").write_text("module.exports = {};", encoding="utf-8")

    git_dir = tmp_path / ".git" / "objects"
    git_dir.mkdir(parents=True)
    (git_dir / "pack").write_text("packdata", encoding="utf-8")

    events = watcher.poll_now()
    assert len(events) == 0
