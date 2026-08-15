"""Provider-neutral, immutable value types for one parsed Markdown note.

`MarkdownNote` is this package's own representation -- deliberately
separate from `app.engine.knowledge.models.KnowledgeDocument`. `source.py`
maps a `MarkdownNote` into a `KnowledgeDocument` at the boundary; nothing
here imports the Knowledge Engine, so this module has no dependency on
Stage 6A at all.

**`content_hash` is whole-file, not body-only.** It is computed (by
`app.integrations.markdown.parser`) from the raw decoded file text,
frontmatter block included, so an edit to frontmatter alone (a changed
tag, a renamed alias) is still a content change for sync purposes -- never
just the chunkable body. `mtime` is carried separately and is explicitly
never part of any hash or identity: two scans of the same bytes at
different `mtime`s must still compare equal on every semantic field.

**Headings here are a flat structural summary, not chunking.** This list
exists for `MarkdownNote.title` fallback and for representing document
structure (Stage 6B, section 7) -- it does not split content into
retrievable pieces. Chunking remains exclusively `app.engine.knowledge.
chunking.chunk_document`'s job; this module never calls it and never
reimplements it.
"""

from dataclasses import dataclass, field
from enum import StrEnum


@dataclass(frozen=True)
class MarkdownFrontmatter:
    """Safely-typed subset of a note's YAML frontmatter. Only the
    documented fields are ever populated -- any other frontmatter key,
    however shaped, is silently dropped, never exposed as an arbitrary
    nested object."""

    title: str | None = None
    description: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    aliases: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class MarkdownHeading:
    """One Markdown heading (`#`..`######`), outside any fenced code
    block, in document order."""

    level: int
    text: str


class MarkdownLinkKind(StrEnum):
    """Whether a link's target is a plain relative Markdown path or an
    external scheme (`http://`, `https://`, `file://`, `mailto:`, ...).
    External targets are represented, never fetched or followed."""

    RELATIVE = "relative"
    EXTERNAL = "external"


@dataclass(frozen=True)
class MarkdownLink:
    """One `[text](target)` Markdown link, as written -- never resolved,
    never fetched. Link *resolution* against a known note set is an
    Obsidian-adapter concern (`app.integrations.obsidian.links`); this
    type only represents what was written in the source text."""

    text: str
    target: str
    kind: MarkdownLinkKind


@dataclass(frozen=True)
class MarkdownNote:
    """One fully-parsed Markdown note, keyed by its root-relative path.

    `relative_path` always uses forward slashes and never contains a
    leading slash, a drive prefix, or a `..` segment -- see
    `app.integrations.markdown.scanner` for the safety guarantee that
    produces it. No field on this type ever carries an absolute host
    path."""

    relative_path: str
    title: str
    frontmatter: MarkdownFrontmatter
    headings: tuple[MarkdownHeading, ...]
    links: tuple[MarkdownLink, ...]
    content: str
    content_hash: str
    mtime: float | None = None


@dataclass(frozen=True)
class NoteFailure:
    """One note that matched the `.md` filter but could not become a valid
    `MarkdownNote`/`KnowledgeDocument` (e.g. empty body, undecodable
    bytes). Reported, never silently dropped and never a raised exception
    that would abort the rest of a scan/sync."""

    relative_path: str
    reason: str


@dataclass(frozen=True)
class MarkdownScanResult:
    """The deterministic result of scanning+parsing one source tree:
    every note that parsed successfully, plus every note that did not,
    both sorted by `relative_path`."""

    notes: tuple[MarkdownNote, ...] = field(default_factory=tuple)
    failures: tuple[NoteFailure, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SyncEntry:
    """One `relative_path` -> `document_id` mapping affected by a sync
    call, sorted by `relative_path` wherever it appears in a
    `SyncResult`."""

    relative_path: str
    document_id: str


@dataclass(frozen=True)
class SyncResult:
    """The deterministic, typed result of one `app.integrations.markdown.
    sync.sync_source` call. `failed` notes are left untouched in both the
    `KnowledgeIndex` and the sync state -- a transient or persistent parse
    failure never silently deletes previously-good indexed content."""

    added: tuple[SyncEntry, ...] = field(default_factory=tuple)
    updated: tuple[SyncEntry, ...] = field(default_factory=tuple)
    deleted: tuple[SyncEntry, ...] = field(default_factory=tuple)
    unchanged: tuple[SyncEntry, ...] = field(default_factory=tuple)
    failed: tuple[NoteFailure, ...] = field(default_factory=tuple)


__all__ = [
    "MarkdownFrontmatter",
    "MarkdownHeading",
    "MarkdownLink",
    "MarkdownLinkKind",
    "MarkdownNote",
    "MarkdownScanResult",
    "NoteFailure",
    "SyncEntry",
    "SyncResult",
]
