"""Tests for `app.engine.knowledge.index.KnowledgeIndex`: add/update/
remove/get/list, stale-chunk cleanup on update, and duplicate handling."""

import pytest

from app.engine.knowledge.chunking import chunk_document
from app.engine.knowledge.errors import MalformedKnowledgeDataError
from app.engine.knowledge.index import KnowledgeIndex
from app.engine.knowledge.models import KnowledgeChunk, KnowledgeDocument


def _doc(
    document_id: str, content: str, *, source_id: str = "src-1", title: str = "T"
) -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id=document_id, source_id=source_id, title=title, content=content
    )


def _chunk(
    document_id: str, ordinal: int, content: str, *, source_id: str = "src-1"
) -> KnowledgeChunk:
    return KnowledgeChunk(
        chunk_id=f"{document_id}::{ordinal}",
        document_id=document_id,
        source_id=source_id,
        content=content,
        ordinal=ordinal,
    )


# --- add / get / list -----------------------------------------------------------------------


def test_empty_index_has_no_documents_or_chunks() -> None:
    index = KnowledgeIndex()
    assert index.list_documents() == []
    assert index.all_chunks() == []
    stats = index.stats()
    assert (stats.document_count, stats.chunk_count) == (0, 0)


def test_add_and_get_document() -> None:
    index = KnowledgeIndex()
    doc = _doc("doc-1", "Paragraph one.\n\nParagraph two.")
    index.upsert_document(doc, chunk_document(doc))
    assert index.get_document("doc-1") == doc
    assert index.get_document("unknown") is None


def test_list_documents_is_sorted_deterministically() -> None:
    index = KnowledgeIndex()
    for document_id in ("doc-c", "doc-a", "doc-b"):
        doc = _doc(document_id, "Some content here.")
        index.upsert_document(doc, chunk_document(doc))
    assert [d.document_id for d in index.list_documents()] == ["doc-a", "doc-b", "doc-c"]


def test_index_chunks_for_document_are_retrievable_and_ordered() -> None:
    index = KnowledgeIndex()
    doc = _doc("doc-1", "Para one.\n\nPara two.\n\nPara three.")
    index.upsert_document(doc, chunk_document(doc))
    chunks = index.get_chunks_for_document("doc-1")
    assert [c.ordinal for c in chunks] == [0, 1, 2]


# --- update / stale chunk cleanup -----------------------------------------------------------


def test_update_document_replaces_content() -> None:
    index = KnowledgeIndex()
    doc_v1 = _doc("doc-1", "Original content.")
    index.upsert_document(doc_v1, chunk_document(doc_v1))
    doc_v2 = _doc("doc-1", "Updated content.")
    index.upsert_document(doc_v2, chunk_document(doc_v2))
    assert index.get_document("doc-1").content == "Updated content."  # type: ignore[union-attr]


def test_update_document_removes_stale_chunks() -> None:
    index = KnowledgeIndex()
    doc_v1 = _doc("doc-1", "Para one.\n\nPara two.\n\nPara three.")
    index.upsert_document(doc_v1, chunk_document(doc_v1))
    assert index.stats().chunk_count == 3

    doc_v2 = _doc("doc-1", "Only one paragraph now.")
    index.upsert_document(doc_v2, chunk_document(doc_v2))
    remaining = index.get_chunks_for_document("doc-1")
    assert len(remaining) == 1
    assert index.stats().chunk_count == 1
    # the old chunk_ids must be genuinely gone, not just unreferenced
    old_chunk_ids = {c.chunk_id for c in chunk_document(doc_v1)}
    new_chunk_ids = {c.chunk_id for c in remaining}
    for old_id in old_chunk_ids - new_chunk_ids:
        assert index.get_chunk(old_id) is None


def test_update_preserves_chunks_that_remain_unchanged() -> None:
    """A chunk whose id is identical before and after an update (same
    document_id/ordinal/content) is not needlessly evicted-then-reinserted
    -- confirmed indirectly by it still being retrievable un-stale."""
    index = KnowledgeIndex()
    content = "Stable para.\n\nWill change."
    doc_v1 = _doc("doc-1", content)
    index.upsert_document(doc_v1, chunk_document(doc_v1))
    stable_chunk_id = chunk_document(doc_v1)[0].chunk_id

    doc_v2 = _doc("doc-1", "Stable para.\n\nHas changed now.")
    index.upsert_document(doc_v2, chunk_document(doc_v2))
    assert index.get_chunk(stable_chunk_id) is not None


# --- remove ----------------------------------------------------------------------------------


def test_remove_document_deletes_document_and_its_chunks() -> None:
    index = KnowledgeIndex()
    doc = _doc("doc-1", "Para one.\n\nPara two.")
    index.upsert_document(doc, chunk_document(doc))
    assert index.remove_document("doc-1") is True
    assert index.get_document("doc-1") is None
    assert index.get_chunks_for_document("doc-1") == []
    assert index.stats().chunk_count == 0


def test_remove_document_is_idempotent_for_unknown_document() -> None:
    index = KnowledgeIndex()
    assert index.remove_document("never-existed") is False


# --- duplicate handling ------------------------------------------------------------------------


def test_upsert_rejects_duplicate_chunk_ids_in_one_call() -> None:
    index = KnowledgeIndex()
    doc = _doc("doc-1", "content")
    duplicate_chunks = [_chunk("doc-1", 0, "a"), _chunk("doc-1", 0, "b")]
    with pytest.raises(MalformedKnowledgeDataError):
        index.upsert_document(doc, duplicate_chunks)


def test_upsert_rejects_chunk_belonging_to_a_different_document() -> None:
    index = KnowledgeIndex()
    doc = _doc("doc-1", "content")
    mismatched_chunk = _chunk("doc-2", 0, "a")
    with pytest.raises(MalformedKnowledgeDataError):
        index.upsert_document(doc, [mismatched_chunk])


def test_same_content_duplicate_chunks_across_documents_are_both_stored() -> None:
    """Two different documents legitimately producing chunks with
    byte-identical content (different chunk_ids since document_id differs)
    must both be stored and independently retrievable -- index-level
    storage never silently deduplicates by content (that is the
    ContextBuilder's job, not the index's)."""
    index = KnowledgeIndex()
    doc_a = _doc("doc-a", "Identical shared text.")
    doc_b = _doc("doc-b", "Identical shared text.")
    index.upsert_document(doc_a, chunk_document(doc_a))
    index.upsert_document(doc_b, chunk_document(doc_b))
    chunk_a = index.get_chunks_for_document("doc-a")[0]
    chunk_b = index.get_chunks_for_document("doc-b")[0]
    assert chunk_a.chunk_id != chunk_b.chunk_id
    assert chunk_a.content_hash == chunk_b.content_hash
    assert index.stats().chunk_count == 2


# --- multiple sources ----------------------------------------------------------------------------


def test_list_documents_filters_by_source() -> None:
    index = KnowledgeIndex()
    doc_a = _doc("doc-a", "content a", source_id="src-a")
    doc_b = _doc("doc-b", "content b", source_id="src-b")
    index.upsert_document(doc_a, chunk_document(doc_a))
    index.upsert_document(doc_b, chunk_document(doc_b))
    assert [d.document_id for d in index.list_documents(source_id="src-a")] == ["doc-a"]
    assert {d.document_id for d in index.list_documents()} == {"doc-a", "doc-b"}


def test_stats_reports_distinct_source_ids() -> None:
    index = KnowledgeIndex()
    doc_a = _doc("doc-a", "content a", source_id="src-a")
    doc_b = _doc("doc-b", "content b", source_id="src-b")
    index.upsert_document(doc_a, chunk_document(doc_a))
    index.upsert_document(doc_b, chunk_document(doc_b))
    assert index.stats().source_ids == ("src-a", "src-b")


def test_upsert_rejects_chunk_id_already_owned_by_another_document() -> None:
    index = KnowledgeIndex()
    doc_a = _doc("doc-a", "content a")
    index.upsert_document(doc_a, chunk_document(doc_a))
    chunk_a = index.get_chunks_for_document("doc-a")[0]

    doc_b = _doc("doc-b", "content b")
    colliding_chunk = _chunk("doc-b", 0, "content b")
    # Manually change chunk_id to match doc_a's chunk_id
    colliding_chunk = KnowledgeChunk(
        chunk_id=chunk_a.chunk_id,
        document_id="doc-b",
        source_id="src-1",
        content="content b",
        ordinal=0,
    )
    with pytest.raises(MalformedKnowledgeDataError, match="already indexed"):
        index.upsert_document(doc_b, [colliding_chunk])

    # doc-a's chunk must be preserved intact
    assert index.get_chunk(chunk_a.chunk_id).document_id == "doc-a"  # type: ignore[union-attr]


def test_update_document_leaves_other_documents_and_their_chunks_unaffected() -> None:
    index = KnowledgeIndex()
    doc_a_v1 = _doc("doc-a", "Para 1.\n\nPara 2.")
    doc_b = _doc("doc-b", "Doc B content.")
    index.upsert_document(doc_a_v1, chunk_document(doc_a_v1))
    index.upsert_document(doc_b, chunk_document(doc_b))

    chunk_b_id = index.get_chunks_for_document("doc-b")[0].chunk_id

    doc_a_v2 = _doc("doc-a", "Updated single para.")
    index.upsert_document(doc_a_v2, chunk_document(doc_a_v2))

    assert index.get_document("doc-b") == doc_b
    assert index.get_chunk(chunk_b_id) is not None
    assert index.get_chunks_for_document("doc-b")[0].chunk_id == chunk_b_id
