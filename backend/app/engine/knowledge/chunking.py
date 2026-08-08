"""Deterministic markdown/plain-text chunking.

**No embeddings, no model calls.** Purely structural: split on heading
boundaries first (so each chunk knows the heading path it lives under),
then on blank-line-separated paragraphs, then -- only if a paragraph still
exceeds the configured maximum size -- a bounded, whitespace-aware
character-count fallback split. Every step is a pure function of
`(content, document_id, source_id, policy)`: no randomness, no current
time, no I/O.

**Same input document + same chunking policy => same semantic chunks.**
`chunk_document` is a pure function; `compute_chunk_id` derives each
chunk's identity from `(document_id, ordinal, content_hash)`, so
re-chunking identical content with an identical policy always yields
identical chunk IDs, content, and ordinals -- verified directly by
`test_engine_knowledge_chunking.py`.

**No empty chunks, no duplication.** Blank lines/whitspace-only paragraphs
are dropped before ever becoming a chunk. The paragraph/fallback-split
algorithm partitions the document's non-blank content into non-overlapping
spans -- by construction, no character of input content is ever emitted
in two different chunks.
"""

import hashlib
import re
from dataclasses import dataclass

from app.engine.knowledge.errors import MalformedKnowledgeDataError
from app.engine.knowledge.models import KnowledgeChunk, KnowledgeDocument

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass(frozen=True)
class ChunkingPolicy:
    """Explicit, documented chunking limits -- no implicit defaults hidden
    in code paths."""

    max_chunk_chars: int = 1000

    def __post_init__(self) -> None:
        if self.max_chunk_chars <= 0:
            raise MalformedKnowledgeDataError("max_chunk_chars must be positive")


def compute_chunk_id(document_id: str, ordinal: int, content_hash: str) -> str:
    """Deterministic chunk identity from semantic position + content --
    never random, never order-of-insertion-dependent."""
    return f"{document_id}::chunk::{ordinal}::{content_hash[:12]}"


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _split_into_heading_scoped_paragraphs(content: str) -> list[tuple[tuple[str, ...], str]]:
    """Split `content` into `(heading_path, paragraph_text)` pairs, in
    document order. A "paragraph" is a maximal run of non-blank,
    non-heading lines; `heading_path` is the stack of enclosing Markdown
    headings (`#`..`######`) active at that point, most specific last."""
    heading_stack: list[tuple[int, str]] = []
    paragraphs: list[tuple[tuple[str, ...], str]] = []
    current_lines: list[str] = []

    def flush() -> None:
        text = "\n".join(current_lines).strip()
        if text:
            paragraphs.append((tuple(text_ for _, text_ in heading_stack), text))
        current_lines.clear()

    for line in content.splitlines():
        heading_match = _HEADING_RE.match(line)
        if heading_match:
            flush()
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()
            heading_stack = [entry for entry in heading_stack if entry[0] < level]
            if heading_text:
                heading_stack.append((level, heading_text))
            continue
        if line.strip() == "":
            flush()
            continue
        current_lines.append(line)
    flush()

    return paragraphs


def _bounded_split(text: str, max_chars: int) -> list[str]:
    """Split `text` into pieces of at most `max_chars`, breaking on the
    nearest preceding whitespace when possible (never mid-word if a
    whitespace break point exists within the bound). Deterministic,
    non-overlapping: every character of `text` appears in exactly one
    output piece."""
    if len(text) <= max_chars:
        return [text]

    pieces: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        split_at = remaining.rfind(" ", 0, max_chars)
        if split_at <= 0:
            split_at = max_chars
        pieces.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip()
    if remaining:
        pieces.append(remaining)
    return pieces


def chunk_document(
    document: KnowledgeDocument, *, policy: ChunkingPolicy | None = None
) -> list[KnowledgeChunk]:
    """Deterministically chunk `document.content` into `KnowledgeChunk`s,
    preferring heading and paragraph boundaries, falling back to bounded
    splitting only when a single paragraph exceeds `policy.max_chunk_chars`.
    Never returns an empty/whitespace-only chunk."""
    policy = policy or ChunkingPolicy()
    paragraphs = _split_into_heading_scoped_paragraphs(document.content)

    chunks: list[KnowledgeChunk] = []
    ordinal = 0
    for heading_path, paragraph in paragraphs:
        for piece in _bounded_split(paragraph, policy.max_chunk_chars):
            piece = piece.strip()
            if not piece:
                continue
            content_hash = _hash(piece)
            chunk_id = compute_chunk_id(document.document_id, ordinal, content_hash)
            chunks.append(
                KnowledgeChunk(
                    chunk_id=chunk_id,
                    document_id=document.document_id,
                    source_id=document.source_id,
                    content=piece,
                    ordinal=ordinal,
                    heading_path=heading_path,
                )
            )
            ordinal += 1

    return chunks


__all__ = ["ChunkingPolicy", "chunk_document", "compute_chunk_id"]
