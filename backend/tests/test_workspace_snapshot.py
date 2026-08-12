"""Tests for `app.engine.orchestration.workspace_snapshot`: bounded,
deterministic before/after workspace snapshotting and diffing -- the real
evidence source for `file_diff` verification (Stage 8C.3 P1 fix, Part 3)."""

from pathlib import Path

from app.engine.orchestration.workspace_snapshot import (
    MAX_DIFF_CHARACTERS,
    diff_snapshots,
    take_snapshot,
)


def test_snapshot_of_missing_directory_is_empty(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    assert take_snapshot(str(missing)) == {}


def test_snapshot_excludes_dependency_and_vcs_directories(tmp_path: Path) -> None:
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.js").write_text("noise", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("noise", encoding="utf-8")
    (tmp_path / "index.js").write_text("real source", encoding="utf-8")

    snapshot = take_snapshot(str(tmp_path))

    assert set(snapshot) == {"index.js"}


def test_diff_detects_added_file(tmp_path: Path) -> None:
    before = take_snapshot(str(tmp_path))
    (tmp_path / "new_file.txt").write_text("hello", encoding="utf-8")
    after = take_snapshot(str(tmp_path))

    files_changed, diff_text = diff_snapshots(before, after)

    assert files_changed == ["new_file.txt"]
    assert "+hello" in diff_text


def test_diff_detects_modified_file_with_real_content(tmp_path: Path) -> None:
    target = tmp_path / "script.js"
    target.write_text("const x = 1;\n", encoding="utf-8")
    before = take_snapshot(str(tmp_path))
    target.write_text("const x = 2;\n", encoding="utf-8")
    after = take_snapshot(str(tmp_path))

    files_changed, diff_text = diff_snapshots(before, after)

    assert files_changed == ["script.js"]
    assert "-const x = 1;" in diff_text
    assert "+const x = 2;" in diff_text


def test_diff_detects_deleted_file(tmp_path: Path) -> None:
    target = tmp_path / "gone.txt"
    target.write_text("bye", encoding="utf-8")
    before = take_snapshot(str(tmp_path))
    target.unlink()
    after = take_snapshot(str(tmp_path))

    files_changed, _diff_text = diff_snapshots(before, after)

    assert files_changed == ["gone.txt"]


def test_diff_of_unchanged_workspace_is_empty(tmp_path: Path) -> None:
    (tmp_path / "stable.txt").write_text("same", encoding="utf-8")
    before = take_snapshot(str(tmp_path))
    after = take_snapshot(str(tmp_path))

    files_changed, diff_text = diff_snapshots(before, after)

    assert files_changed == []
    assert diff_text == ""


def test_binary_or_oversized_file_change_reported_without_content(tmp_path: Path) -> None:
    target = tmp_path / "asset.bin"
    target.write_bytes(b"\x00\x01\x02\xff\xfe")
    before = take_snapshot(str(tmp_path))
    target.write_bytes(b"\x00\x01\x02\xff\xfe\xaa")
    after = take_snapshot(str(tmp_path))

    files_changed, diff_text = diff_snapshots(before, after)

    assert files_changed == ["asset.bin"]
    assert "binary or oversized file changed" in diff_text


def test_diff_text_is_bounded(tmp_path: Path) -> None:
    before: dict = {}
    after = {}
    from app.engine.orchestration.workspace_snapshot import FileState

    # A synthetic, deliberately oversized set of changes to prove the
    # bound is enforced regardless of how much real content changed.
    for i in range(50):
        after[f"file_{i}.txt"] = FileState(size=10_000, content="x" * 10_000)

    _files_changed, diff_text = diff_snapshots(before, after)

    assert len(diff_text) <= MAX_DIFF_CHARACTERS + len("\n... (diff truncated)")
    assert diff_text.endswith("... (diff truncated)")
