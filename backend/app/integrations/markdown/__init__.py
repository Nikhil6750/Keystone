"""Stage 6B: Generic Markdown Knowledge Source.

Architecture:

    Plain Markdown / Git docs / Foam workspace
        -> MarkdownKnowledgeSource (this package)
        -> KnowledgeDocument (app.engine.knowledge.models, unmodified)
        -> app.engine.knowledge chunking / index / retrieval / ContextBuilder
           (Stage 6A, unmodified; Stage 7.5 adaptive retrieval wraps it,
           also unmodified)

Nothing in this package depends on Obsidian, executes Markdown/HTML/code,
or writes to a source directory. `app.integrations.obsidian` is the
*only* consumer of this package that adds vault-specific behavior
(`.obsidian/**` exclusion, `[[wikilink]]` parsing, link resolution,
backlink graph) -- generic Markdown/Git-docs/Foam logic never imports
from, or depends on, that package.
"""

from app.integrations.markdown.errors import (
    MarkdownIntegrationError,
    MarkdownSourceConfigError,
    NoteParseError,
    PathSafetyError,
)
from app.integrations.markdown.models import (
    MarkdownFrontmatter,
    MarkdownHeading,
    MarkdownLink,
    MarkdownLinkKind,
    MarkdownNote,
    MarkdownScanResult,
    NoteFailure,
    SyncEntry,
    SyncResult,
)
from app.integrations.markdown.parser import parse_markdown_note
from app.integrations.markdown.scanner import (
    resolve_relative_path,
    resolve_root,
    scan_markdown_files,
)
from app.integrations.markdown.source import (
    SOURCE_KIND_MARKDOWN,
    MarkdownKnowledgeSource,
    MarkdownSourceConfig,
    build_document_id,
    note_to_document,
)
from app.integrations.markdown.state import (
    DocumentSyncState,
    InMemoryKnowledgeSourceStateRepository,
    KnowledgeSourceStateRepository,
)
from app.integrations.markdown.sync import sync_source

__all__ = [
    "SOURCE_KIND_MARKDOWN",
    "DocumentSyncState",
    "InMemoryKnowledgeSourceStateRepository",
    "KnowledgeSourceStateRepository",
    "MarkdownFrontmatter",
    "MarkdownHeading",
    "MarkdownIntegrationError",
    "MarkdownKnowledgeSource",
    "MarkdownLink",
    "MarkdownLinkKind",
    "MarkdownNote",
    "MarkdownScanResult",
    "MarkdownSourceConfig",
    "MarkdownSourceConfigError",
    "NoteFailure",
    "NoteParseError",
    "PathSafetyError",
    "SyncEntry",
    "SyncResult",
    "build_document_id",
    "note_to_document",
    "parse_markdown_note",
    "resolve_relative_path",
    "resolve_root",
    "scan_markdown_files",
    "sync_source",
]
