"""Tests for `app.integrations.markdown.scanner`: discovery, exclusions,
deterministic ordering, and root-escape prevention."""

import os
from pathlib import Path

import pytest

from app.integrations.markdown.errors import MarkdownSourceConfigError, PathSafetyError
from app.integrations.markdown.scanner import (
    resolve_relative_path,
    resolve_root,
    scan_markdown_files,
)


def _write(root: Path, relative_path: str, content: str = "# Title\n\nBody.\n") -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# --- basic scanning -----------------------------------------------------------------


def test_finds_markdown_files_only(tmp_path: Path) -> None:
    _write(tmp_path, "architecture.md")
    _write(tmp_path, "notes/api.md")
    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n")
    (tmp_path / "notes.txt").write_text("not markdown", encoding="utf-8")

    found = scan_markdown_files(resolve_root(tmp_path))

    assert found == ["architecture.md", "notes/api.md"]


def test_case_insensitive_extension(tmp_path: Path) -> None:
    _write(tmp_path, "README.MD")
    found = scan_markdown_files(resolve_root(tmp_path))
    assert found == ["README.MD"]


def test_empty_directory_returns_empty_list(tmp_path: Path) -> None:
    assert scan_markdown_files(resolve_root(tmp_path)) == []


# --- exclusions ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "excluded_dir",
    [".git", "node_modules", "__pycache__", "dist", "build", ".cache"],
)
def test_default_exclusions_are_pruned(tmp_path: Path, excluded_dir: str) -> None:
    _write(tmp_path, "kept.md")
    _write(tmp_path, f"{excluded_dir}/should-not-be-found.md")

    found = scan_markdown_files(resolve_root(tmp_path))

    assert found == ["kept.md"]


def test_extra_excluded_dir_names_are_honored(tmp_path: Path) -> None:
    _write(tmp_path, "kept.md")
    _write(tmp_path, ".obsidian/plugins/plugin.md")

    found = scan_markdown_files(
        resolve_root(tmp_path), extra_excluded_dir_names=frozenset({".obsidian"})
    )

    assert found == ["kept.md"]


def test_os_junk_files_are_excluded(tmp_path: Path) -> None:
    _write(tmp_path, "kept.md")
    (tmp_path / "Thumbs.db").write_bytes(b"junk")
    (tmp_path / ".DS_Store").write_bytes(b"junk")

    found = scan_markdown_files(resolve_root(tmp_path))

    assert found == ["kept.md"]


def test_binary_and_private_files_never_indexed(tmp_path: Path) -> None:
    _write(tmp_path, "kept.md")
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")
    (tmp_path / "id_rsa").write_text("-----BEGIN PRIVATE KEY-----", encoding="utf-8")
    (tmp_path / "data.sqlite3").write_bytes(b"SQLite format 3\x00")
    (tmp_path / "diagram.pdf").write_bytes(b"%PDF-1.4")

    found = scan_markdown_files(resolve_root(tmp_path))

    assert found == ["kept.md"]


# --- deterministic order --------------------------------------------------------------


def test_scan_order_is_deterministic_regardless_of_creation_order(tmp_path: Path) -> None:
    creation_order = ["zeta.md", "alpha/one.md", "beta.md", "alpha/two.md"]
    for relative_path in creation_order:
        _write(tmp_path, relative_path)

    first = scan_markdown_files(resolve_root(tmp_path))
    second = scan_markdown_files(resolve_root(tmp_path))

    assert first == second
    assert first == sorted(first)
    assert first == ["alpha/one.md", "alpha/two.md", "beta.md", "zeta.md"]


# --- root resolution / config safety ---------------------------------------------------


def test_resolve_root_rejects_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(MarkdownSourceConfigError):
        resolve_root(tmp_path / "does-not-exist")


def test_resolve_root_rejects_a_file(tmp_path: Path) -> None:
    file_path = tmp_path / "not-a-dir.md"
    file_path.write_text("x", encoding="utf-8")
    with pytest.raises(MarkdownSourceConfigError):
        resolve_root(file_path)


# --- path traversal / escape safety -----------------------------------------------------


def test_resolve_relative_path_rejects_traversal(tmp_path: Path) -> None:
    root = resolve_root(tmp_path)
    with pytest.raises(PathSafetyError):
        resolve_relative_path(root, "../../secret.md")


def test_resolve_relative_path_rejects_absolute_path(tmp_path: Path) -> None:
    root = resolve_root(tmp_path)
    with pytest.raises(PathSafetyError):
        resolve_relative_path(root, "/etc/passwd")


def test_resolve_relative_path_rejects_blank(tmp_path: Path) -> None:
    root = resolve_root(tmp_path)
    with pytest.raises(PathSafetyError):
        resolve_relative_path(root, "")


def test_resolve_relative_path_accepts_valid_nested_path(tmp_path: Path) -> None:
    root = resolve_root(tmp_path)
    _write(tmp_path, "docs/architecture.md")
    resolved = resolve_relative_path(root, "docs/architecture.md")
    assert resolved == (root / "docs" / "architecture.md").resolve()


@pytest.mark.skipif(os.name != "nt" and not hasattr(os, "symlink"), reason="symlinks unsupported")
def test_symlinked_file_escaping_root_is_silently_excluded(tmp_path: Path) -> None:
    outside_dir = tmp_path.parent / f"outside-{tmp_path.name}"
    outside_dir.mkdir(exist_ok=True)
    secret = outside_dir / "secret.md"
    secret.write_text("# Secret\n\nShould never be indexed.\n", encoding="utf-8")

    root_dir = tmp_path / "vault"
    root_dir.mkdir()
    _write(root_dir, "kept.md")
    link_path = root_dir / "escape.md"
    try:
        os.symlink(secret, link_path)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted in this environment")

    found = scan_markdown_files(resolve_root(root_dir))

    assert found == ["kept.md"]


@pytest.mark.skipif(os.name != "nt" and not hasattr(os, "symlink"), reason="symlinks unsupported")
def test_symlinked_directory_escaping_root_is_not_traversed(tmp_path: Path) -> None:
    outside_dir = tmp_path.parent / f"outside-dir-{tmp_path.name}"
    outside_dir.mkdir(exist_ok=True)
    (outside_dir / "secret.md").write_text("# Secret\n\nBody.\n", encoding="utf-8")

    root_dir = tmp_path / "vault"
    root_dir.mkdir()
    _write(root_dir, "kept.md")
    link_dir = root_dir / "escape-dir"
    try:
        os.symlink(outside_dir, link_dir, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted in this environment")

    found = scan_markdown_files(resolve_root(root_dir))

    assert found == ["kept.md"]
