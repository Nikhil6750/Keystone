"""`MarkdownKnowledgeSource`: the generic, read-only `KnowledgeSource`
(`app.engine.knowledge.source.KnowledgeSource`) implementation for a plain
directory of `.md` files.

Works for a bare `docs/` folder, a Git-tracked documentation tree, or a
Foam-style workspace -- no `.obsidian`-specific assumption anywhere in
this module. `app.integrations.obsidian.adapter.ObsidianVaultAdapter`
composes one of these (pointed at a vault root, with `.obsidian/**`
added to its exclusions) rather than reimplementing scanning, parsing, or
`KnowledgeDocument` mapping.

**Safe, root-relative document identity.** `build_document_id` is a pure
function of `(source_id, relative_path)` -- no random UUID, no
timestamp -- so re-scanning identical notes always yields identical
`document_id`s, and a note's identity survives an unrelated edit but not
a rename (a rename is a different `relative_path`, hence structurally a
different `document_id`; see `app.integrations.markdown.sync` for how
that surfaces as "old removed, new added").
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.engine.knowledge.errors import KnowledgeEngineError
from app.engine.knowledge.models import KnowledgeDocument
from app.integrations.markdown.errors import (
    MarkdownSourceConfigError,
    NoteParseError,
    PathSafetyError,
)
from app.integrations.markdown.models import MarkdownNote, MarkdownScanResult, NoteFailure
from app.integrations.markdown.parser import parse_markdown_note
from app.integrations.markdown.scanner import (
    resolve_relative_path,
    resolve_root,
    scan_markdown_files,
)

SOURCE_KIND_MARKDOWN = "markdown"


@dataclass(frozen=True)
class MarkdownSourceConfig:
    """Explicit configuration for one `MarkdownKnowledgeSource`. `root`
    may be any path-like value; it is canonicalized once, at
    `MarkdownKnowledgeSource` construction, via `scanner.resolve_root`."""

    root: str | Path
    source_id: str
    source_kind: str = SOURCE_KIND_MARKDOWN
    extra_excluded_dir_names: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise MarkdownSourceConfigError("source_id must not be blank")
        if not self.source_kind.strip():
            raise MarkdownSourceConfigError("source_kind must not be blank")


def build_document_id(source_id: str, relative_path: str) -> str:
    """Deterministic, safe document identity -- no random UUID, no
    current timestamp, never trusted from caller input elsewhere."""
    return f"{source_id}::{relative_path}"


def note_to_document(source_id: str, source_kind: str, note: MarkdownNote) -> KnowledgeDocument:
    """Map one parsed `MarkdownNote` into a Stage 6A `KnowledgeDocument`.
    Metadata is restricted to safe, root-relative facts (`source_kind`,
    `relative_path`, whole-file `content_hash`, `tags`, `aliases`,
    optional `description`) -- never an absolute host path. `mtime`, if
    known, becomes `modified_at`: operational metadata only, never part
    of `document_id` or of `KnowledgeDocument`'s own `content_hash`
    (which `KnowledgeDocument.__post_init__` derives from `content`)."""
    metadata = {
        "source_kind": source_kind,
        "relative_path": note.relative_path,
        "content_hash": note.content_hash,
        "tags": ",".join(note.frontmatter.tags),
        "aliases": ",".join(note.frontmatter.aliases),
    }
    if note.frontmatter.description:
        metadata["description"] = note.frontmatter.description

    modified_at = datetime.fromtimestamp(note.mtime, tz=UTC) if note.mtime is not None else None

    return KnowledgeDocument(
        document_id=build_document_id(source_id, note.relative_path),
        source_id=source_id,
        title=note.title,
        content=note.content,
        metadata=metadata,
        modified_at=modified_at,
    )


class MarkdownKnowledgeSource:
    """Read-only `KnowledgeSource`: never writes, renames, moves, deletes,
    or reformats anything beneath its root. `scan()` opens each
    discovered `.md` file for reading exactly once per call, nothing
    else."""

    def __init__(self, config: MarkdownSourceConfig) -> None:
        self._config = config
        self._root = resolve_root(config.root)

    @property
    def source_id(self) -> str:
        return self._config.source_id

    @property
    def source_kind(self) -> str:
        return self._config.source_kind

    @property
    def root(self) -> Path:
        return self._root

    def scan(self) -> MarkdownScanResult:
        """Every note beneath the configured root, parsed, plus every
        note that could not become a valid `MarkdownNote`/`KnowledgeDocument`
        (empty body, undecodable bytes, unreadable file, or content Stage
        6A itself rejects as unsafe/malformed) -- both sorted by
        `relative_path` for deterministic output regardless of filesystem
        iteration order. One bad note never aborts the rest of the scan."""
        relative_paths = scan_markdown_files(
            self._root, extra_excluded_dir_names=self._config.extra_excluded_dir_names
        )
        notes: list[MarkdownNote] = []
        failures: list[NoteFailure] = []
        for relative_path in relative_paths:
            try:
                # Re-verify containment at the moment of the actual read,
                # not just at scan-discovery time -- closes the narrow
                # window where a path could be swapped (e.g. a symlink
                # replaced) between discovery and read.
                absolute_path = resolve_relative_path(self._root, relative_path)
                raw_text = absolute_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError, PathSafetyError) as exc:
                failures.append(
                    NoteFailure(relative_path=relative_path, reason=f"unreadable: {exc}")
                )
                continue
            mtime = absolute_path.stat().st_mtime
            try:
                note = parse_markdown_note(relative_path, raw_text, mtime=mtime)
                # Validate it can actually become a `KnowledgeDocument` now
                # (e.g. Stage 6A rejects a frontmatter tag/alias value that
                # happens to look like an absolute filesystem path) -- a
                # rejection here must be an isolated `NoteFailure`, never an
                # exception that aborts the rest of the scan.
                note_to_document(self._config.source_id, self._config.source_kind, note)
            except NoteParseError as exc:
                failures.append(NoteFailure(relative_path=relative_path, reason=str(exc)))
                continue
            except KnowledgeEngineError as exc:
                failures.append(
                    NoteFailure(relative_path=relative_path, reason=f"unsafe or malformed: {exc}")
                )
                continue
            notes.append(note)
        return MarkdownScanResult(
            notes=tuple(sorted(notes, key=lambda n: n.relative_path)),
            failures=tuple(sorted(failures, key=lambda f: f.relative_path)),
        )

    def list_documents(self) -> list[KnowledgeDocument]:
        """`KnowledgeSource` Protocol entry point. A note that fails to
        parse is silently skipped here, matching the Protocol's plain
        `list[KnowledgeDocument]` return shape -- call `scan()` directly
        to also observe failures (as `app.integrations.markdown.sync.
        sync_source` does)."""
        scan_result = self.scan()
        return [
            note_to_document(self._config.source_id, self._config.source_kind, note)
            for note in scan_result.notes
        ]


__all__ = [
    "MarkdownKnowledgeSource",
    "MarkdownSourceConfig",
    "SOURCE_KIND_MARKDOWN",
    "build_document_id",
    "note_to_document",
]
