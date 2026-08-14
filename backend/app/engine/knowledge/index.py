"""`KnowledgeIndex`: in-memory storage for `KnowledgeDocument`s and their
`KnowledgeChunk`s -- Stage 6A's only index implementation. No database, no
persistence; a fresh process starts with an empty index (Stage 6B adds
real persistence without changing this class's public shape).

**Updating a document never leaves stale chunks behind.** `upsert_document`
is the single, atomic entry point for "add or update": it replaces the
document record and re-indexes its chunks in one call, removing every
previously-indexed chunk for that `document_id` whose `chunk_id` is not
part of the new chunk set. There is no separate "index chunks" call that
could be invoked out of sync with the document it belongs to -- that
class of bug (stale chunks surviving a document update) is structurally
impossible here, not just tested against.

**Deterministic ordering.** `list_documents`/`all_chunks`/
`get_chunks_for_document` all return results sorted by a stable key
(`document_id`, then `ordinal` for chunks) -- never raw dict/insertion
order, so index state and any code iterating over it behaves identically
regardless of the order documents were added in.
"""

from dataclasses import dataclass

from app.engine.knowledge.errors import MalformedKnowledgeDataError
from app.engine.knowledge.models import KnowledgeChunk, KnowledgeDocument


@dataclass(frozen=True)
class IndexStats:
    """A deterministic snapshot of index size -- useful for "empty index"
    checks without exposing internal storage."""

    document_count: int
    chunk_count: int
    source_ids: tuple[str, ...]


class KnowledgeIndex:
    """Mutable, in-memory knowledge store. Not thread-safe (matches every
    other in-memory engine-layer registry in this codebase, e.g.
    `CircuitBreakerRegistry` -- single-process, single-writer use)."""

    def __init__(self) -> None:
        self._documents: dict[str, KnowledgeDocument] = {}
        self._chunks: dict[str, KnowledgeChunk] = {}
        self._chunk_ids_by_document: dict[str, set[str]] = {}

    def upsert_document(self, document: KnowledgeDocument, chunks: list[KnowledgeChunk]) -> None:
        """Add `document` (or replace it, if `document.document_id` is
        already indexed) together with its `chunks`. Any chunk previously
        indexed for this `document_id` that is not part of the new
        `chunks` list is removed -- no stale chunks ever survive an
        update."""
        mismatched = [
            chunk.chunk_id
            for chunk in chunks
            if chunk.document_id != document.document_id or chunk.source_id != document.source_id
        ]
        if mismatched:
            raise MalformedKnowledgeDataError(
                f"chunk(s) {mismatched} do not belong to document "
                f"{document.document_id!r} (source {document.source_id!r})"
            )
        chunk_ids = [chunk.chunk_id for chunk in chunks]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise MalformedKnowledgeDataError(
                f"duplicate chunk_id(s) supplied for document {document.document_id!r}"
            )
        colliding = [
            chunk.chunk_id
            for chunk in chunks
            if chunk.chunk_id in self._chunks
            and self._chunks[chunk.chunk_id].document_id != document.document_id
        ]
        if colliding:
            raise MalformedKnowledgeDataError(
                f"chunk_id(s) {colliding} are already indexed by another document"
            )

        previous_chunk_ids = self._chunk_ids_by_document.get(document.document_id, set())
        new_chunk_ids = set(chunk_ids)
        for stale_chunk_id in previous_chunk_ids - new_chunk_ids:
            self._chunks.pop(stale_chunk_id, None)

        self._documents[document.document_id] = document
        for chunk in chunks:
            self._chunks[chunk.chunk_id] = chunk
        self._chunk_ids_by_document[document.document_id] = new_chunk_ids

    def remove_document(self, document_id: str) -> bool:
        """Remove `document_id` and every chunk indexed for it. Idempotent:
        returns `True` if it existed and was removed, `False` if it was
        already absent (never raises for a routine "already gone" cleanup
        call)."""
        if document_id not in self._documents:
            return False
        for chunk_id in self._chunk_ids_by_document.pop(document_id, set()):
            self._chunks.pop(chunk_id, None)
        del self._documents[document_id]
        return True

    def get_document(self, document_id: str) -> KnowledgeDocument | None:
        return self._documents.get(document_id)

    def list_documents(self, *, source_id: str | None = None) -> list[KnowledgeDocument]:
        documents: list[KnowledgeDocument] = list(self._documents.values())
        if source_id is not None:
            documents = [doc for doc in documents if doc.source_id == source_id]
        return sorted(documents, key=lambda doc: doc.document_id)

    def get_chunk(self, chunk_id: str) -> KnowledgeChunk | None:
        return self._chunks.get(chunk_id)

    def get_chunks_for_document(self, document_id: str) -> list[KnowledgeChunk]:
        chunk_ids = self._chunk_ids_by_document.get(document_id, set())
        chunks = [self._chunks[chunk_id] for chunk_id in chunk_ids]
        return sorted(chunks, key=lambda chunk: chunk.ordinal)

    def all_chunks(self) -> list[KnowledgeChunk]:
        return sorted(self._chunks.values(), key=lambda chunk: (chunk.document_id, chunk.ordinal))

    def stats(self) -> IndexStats:
        return IndexStats(
            document_count=len(self._documents),
            chunk_count=len(self._chunks),
            source_ids=tuple(sorted({doc.source_id for doc in self._documents.values()})),
        )


__all__ = ["IndexStats", "KnowledgeIndex"]
