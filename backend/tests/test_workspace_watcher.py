"""Unit tests for WorkspaceWatcher (Live Workspace File Activity Monitor)."""

import os
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
    mtime = test_file.stat().st_mtime + 2.0
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


def test_concurrent_file_attribution(tmp_path: Path) -> None:
    watcher = WorkspaceWatcher(tmp_path)
    watcher.poll_now()

    # Register concurrent tasks A and B
    watcher.register_active_task(task_id="T1", agent_id="agent-a", target_files=["a.py"])
    watcher.register_active_task(task_id="T2", agent_id="agent-b", target_files=["b.py"])

    # 1. Create a.py -> attributed to Task T1 / Agent agent-a
    (tmp_path / "a.py").write_text("def a(): pass", encoding="utf-8")
    events_a = watcher.poll_now()
    assert len(events_a) == 1
    assert events_a[0].relative_path == "a.py"
    assert events_a[0].task_id == "T1"
    assert events_a[0].agent_id == "agent-a"

    # 2. Create b.py -> attributed to Task T2 / Agent agent-b
    (tmp_path / "b.py").write_text("def b(): pass", encoding="utf-8")
    events_b = watcher.poll_now()
    assert len(events_b) == 1
    assert events_b[0].relative_path == "b.py"
    assert events_b[0].task_id == "T2"
    assert events_b[0].agent_id == "agent-b"

    # 3. Create unowned/shared file (e.g. shared.json) during multi-task -> (None, None)
    (tmp_path / "shared.json").write_text("{}", encoding="utf-8")
    events_shared = watcher.poll_now()
    assert len(events_shared) == 1
    assert events_shared[0].relative_path == "shared.json"
    assert events_shared[0].task_id is None
    assert events_shared[0].agent_id is None

    # 4. Modifying a.py while both active is attributed to Task T1 (agent-b cannot steal)
    (tmp_path / "a.py").write_text("def a(): return 1", encoding="utf-8")
    mtime = (tmp_path / "a.py").stat().st_mtime + 2.0
    os.utime(str(tmp_path / "a.py"), (mtime, mtime))
    events_a_mod = watcher.poll_now()
    assert len(events_a_mod) == 1
    assert events_a_mod[0].relative_path == "a.py"
    assert events_a_mod[0].task_id == "T1"
    assert events_a_mod[0].agent_id == "agent-a"

    # 5. Unregister T1 -> only T2 remaining
    watcher.unregister_active_task("T1")
    (tmp_path / "c.py").write_text("def c(): pass", encoding="utf-8")
    events_c = watcher.poll_now()
    assert len(events_c) == 1
    assert events_c[0].relative_path == "c.py"
    assert events_c[0].task_id == "T2"
    assert events_c[0].agent_id == "agent-b"
