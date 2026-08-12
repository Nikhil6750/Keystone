"""Bounded, deterministic workspace filesystem snapshotting and diffing --
the real evidence source for Stage 4E's `file_diff` evaluator
(`app.engine.verification.evaluators.evaluate_file_diff`) once a step has
actually executed against a real, persistent workspace (see
`app.engine.orchestration.evidence_collector`).

Never derives evidence from a model's prose claim about what it changed --
only from files Keystone itself can see on disk, before and after a step
ran. Bounded on every axis (file count, per-file size, total diff length)
so a pathological workspace can never make verification hang or leak an
unbounded amount of content.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

MAX_SNAPSHOT_FILES = 2000
MAX_TEXT_FILE_BYTES = 256_000
MAX_DIFF_CHARACTERS = 20_000

# Shared with `evidence_collector.py`'s own discovery walk -- directories
# whose contents are never real evidence of *this* project's own changes
# (dependency trees, VCS internals, build/cache output).
EXCLUDED_DIR_NAMES = frozenset(
    {
        "node_modules",
        ".git",
        ".venv",
        "venv",
        "env",
        "dist",
        "build",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".next",
        "coverage",
        ".idea",
        ".vscode",
        ".tox",
        "site-packages",
    }
)


@dataclass(frozen=True)
class FileState:
    """One file's observed state. `content` is `None` for binary/oversized
    files -- their content is never read, only their size, so a changed
    binary/oversized file is still detected as changed without ever being
    fully buffered into memory or echoed into evidence."""

    size: int
    content: str | None


def _iter_candidate_files(root: Path) -> list[Path]:
    """Deterministic (sorted), bounded, excluded-dir-aware file walk."""
    results: list[Path] = []
    stack: list[Path] = [root]
    while stack and len(results) < MAX_SNAPSHOT_FILES:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name not in EXCLUDED_DIR_NAMES:
                    stack.append(entry)
            elif entry.is_file():
                results.append(entry)
                if len(results) >= MAX_SNAPSHOT_FILES:
                    break
    return sorted(results)


def take_snapshot(workspace_root: str) -> dict[str, FileState]:
    """Read every non-excluded file under `workspace_root` (bounded count
    and per-file size). Returns `{}` if `workspace_root` does not exist or
    is not a directory -- never raises, since a missing workspace is simply
    "nothing observed yet", not an error."""
    root = Path(workspace_root)
    if not root.is_dir():
        return {}
    snapshot: dict[str, FileState] = {}
    for path in _iter_candidate_files(root):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        relative = path.relative_to(root).as_posix()
        if size > MAX_TEXT_FILE_BYTES:
            snapshot[relative] = FileState(size=size, content=None)
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            snapshot[relative] = FileState(size=size, content=None)
            continue
        snapshot[relative] = FileState(size=size, content=content)
    return snapshot


def _describe_change(path: str, before: FileState | None, after: FileState | None) -> str:
    before_unreadable = before is not None and before.content is None
    after_unreadable = after is not None and after.content is None
    if before_unreadable or after_unreadable:
        before_size = before.size if before else 0
        after_size = after.size if after else 0
        return f"# {path}: binary or oversized file changed ({before_size} -> {after_size} bytes)"

    before_text = (before.content if before is not None else None) or ""
    after_text = (after.content if after is not None else None) or ""
    before_lines = before_text.splitlines(keepends=True)
    after_lines = after_text.splitlines(keepends=True)
    diff_lines = list(
        difflib.unified_diff(before_lines, after_lines, fromfile=f"a/{path}", tofile=f"b/{path}")
    )
    return "".join(diff_lines) if diff_lines else f"# {path}: changed"


def diff_snapshots(
    before: dict[str, FileState], after: dict[str, FileState]
) -> tuple[list[str], str]:
    """Compare two snapshots. Returns `(files_changed, diff_text)`:
    `files_changed` is every relative path added, removed, or modified
    (size or content differs), sorted for determinism. `diff_text` is a
    real unified diff (via `difflib`) for changed text files, and a plain
    factual line (never fabricated content) for binary/oversized files --
    bounded to `MAX_DIFF_CHARACTERS`."""
    changed: list[str] = []
    diff_parts: list[str] = []
    for path in sorted(set(before) | set(after)):
        before_state = before.get(path)
        after_state = after.get(path)
        if before_state == after_state:
            continue
        changed.append(path)
        diff_parts.append(_describe_change(path, before_state, after_state))

    diff_text = "\n".join(diff_parts)
    if len(diff_text) > MAX_DIFF_CHARACTERS:
        diff_text = diff_text[:MAX_DIFF_CHARACTERS] + "\n... (diff truncated)"
    return changed, diff_text


__all__ = [
    "EXCLUDED_DIR_NAMES",
    "MAX_DIFF_CHARACTERS",
    "MAX_SNAPSHOT_FILES",
    "MAX_TEXT_FILE_BYTES",
    "FileState",
    "diff_snapshots",
    "take_snapshot",
]
