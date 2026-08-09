"""Filesystem discovery of `.md` files beneath a canonicalized root, with
root-escape prevention and a fixed exclusion set.

**Root-escape prevention.** `resolve_root` canonicalizes the configured
root once (`Path.resolve(strict=True)`, which also resolves symlinks and,
on Windows, NTFS junctions/reparse points). `scan_markdown_files` then
resolves *every candidate file* the same way and verifies the result is
still beneath that canonical root before including it -- a symlinked file
(or a directory junction) pointing outside the root is silently excluded,
the same way an excluded directory is, never surfaced as an error that
would leak the outside-root path. `os.walk(..., followlinks=False)`
additionally prevents descending into a symlinked *directory* at all.

**Only `.md` files, ever.** The extension check is the single point where
"images/PDFs/binary attachments/`.env`/private keys/database files are
never indexed" is enforced -- nothing later in the pipeline re-opens a
file this function did not yield.

**Deterministic order.** Directory and file names are sorted at every
level of the walk, and the final list is sorted by relative path -- the
result never depends on the underlying filesystem's native iteration
order.
"""

import os
from pathlib import Path

from app.integrations.markdown.errors import MarkdownSourceConfigError, PathSafetyError

# Directory names excluded everywhere, regardless of nesting depth.
DEFAULT_EXCLUDED_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        "dist",
        "build",
        ".cache",
    }
)

# Exact file names treated as OS/editor junk, never indexed even though
# they could theoretically end in `.md` (they never do, but exclusion is
# checked before the extension check for clarity and defense in depth).
_EXCLUDED_FILE_NAMES: frozenset[str] = frozenset({"Thumbs.db", ".DS_Store", "desktop.ini"})


def resolve_root(root: str | Path) -> Path:
    """Canonicalize `root` into an absolute, symlink-resolved `Path`.
    Raises `MarkdownSourceConfigError` if it does not exist or is not a
    directory -- never silently falls back to a different location."""
    try:
        resolved = Path(root).resolve(strict=True)
    except OSError as exc:
        raise MarkdownSourceConfigError(f"root does not exist or is not accessible: {exc}") from exc
    if not resolved.is_dir():
        raise MarkdownSourceConfigError("root must be an existing directory")
    return resolved


def _is_within_root(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def resolve_relative_path(root: Path, relative_path: str) -> Path:
    """Resolve `relative_path` (forward-slash, root-relative) against the
    already-canonicalized `root`, raising `PathSafetyError` if the result
    would not stay beneath `root` -- the shared defense-in-depth check
    every read of a single known note goes through, not just the bulk
    scan."""
    if not relative_path or relative_path.startswith(("/", "\\")):
        raise PathSafetyError("relative_path must be a non-empty, non-absolute path")
    candidate = (root / Path(relative_path)).resolve()
    if not _is_within_root(candidate, root):
        raise PathSafetyError("relative_path resolves outside the configured root")
    return candidate


def scan_markdown_files(
    root: Path, *, extra_excluded_dir_names: frozenset[str] = frozenset()
) -> list[str]:
    """Every `.md` file beneath `root` (already canonicalized via
    `resolve_root`), as root-relative, forward-slash, sorted paths.
    Excluded directories are pruned before descent; a file whose resolved
    real path escapes `root` (symlink/junction) is silently skipped, never
    raised as an error."""
    excluded_dir_names = DEFAULT_EXCLUDED_DIR_NAMES | extra_excluded_dir_names
    relative_paths: list[str] = []

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if name not in excluded_dir_names)
        for filename in sorted(filenames):
            if filename in _EXCLUDED_FILE_NAMES:
                continue
            if not filename.lower().endswith(".md"):
                continue
            candidate = Path(dirpath) / filename
            try:
                real_candidate = candidate.resolve(strict=True)
            except OSError:
                continue
            if not _is_within_root(real_candidate, root):
                continue
            relative_paths.append(real_candidate.relative_to(root).as_posix())

    return sorted(set(relative_paths))


__all__ = [
    "DEFAULT_EXCLUDED_DIR_NAMES",
    "resolve_relative_path",
    "resolve_root",
    "scan_markdown_files",
]
