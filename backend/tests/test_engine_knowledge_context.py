"""Tests for `app.engine.knowledge.context.ContextBuilder`: budget
respect, provenance preservation, dedup, and deterministic selection."""

import pytest

from app.engine.knowledge.chunking import chunk_document
from app.engine.knowledge.context import ContextBudget, ContextBuilder
from app.engine.knowledge.errors import MalformedKnowledgeDataError
from app.engine.knowledge.index import KnowledgeIndex
from app.engine.knowledge.models import KnowledgeDocument
from app.engine.knowledge.retrieval import KnowledgeSearchRequest, KnowledgeSearchResult, search


def _doc(document_id: str, content: str, *, title: str = "Doc") -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id=document_id, source_id="src-1", title=title, content=content
    )


def _index(*docs: KnowledgeDocument) -> KnowledgeIndex:
    index = KnowledgeIndex()
    for doc in docs:
        index.upsert_document(doc, chunk_document(doc))
    return index


def test_context_respects_max_chunks_budget() -> None:
    docs = [_doc(f"doc-{i}", f"reliability discussion {i}") for i in range(10)]
    index = _index(*docs)
    results = search(index, KnowledgeSearchRequest(query="reliability", limit=10))
    context = ContextBuilder().build(results, ContextBudget(max_chunks=3, max_total_chars=10_000))
    assert len(context.chunks) == 3
    assert context.truncated is True


def test_context_respects_max_total_chars_budget() -> None:
    docs = [_doc(f"doc-{i}", "reliability " * 50) for i in range(5)]
    index = _index(*docs)
    results = search(index, KnowledgeSearchRequest(query="reliability", limit=5))
    context = ContextBuilder().build(results, ContextBudget(max_chunks=5, max_total_chars=100))
    assert context.total_chars <= 100
    assert all(len(c.content) <= 100 for c in context.chunks)


def test_context_never_partially_truncates_a_chunk() -> None:
    """A chunk that cannot fit within the remaining budget is skipped
    whole, never sliced -- the selected chunk's content matches a real,
    complete chunk's content exactly, never a cut-down fragment."""
    doc_big = _doc("doc-big", "x" * 500)
    doc_small = _doc("doc-small", "reliability content small")
    index = _index(doc_big, doc_small)
    big_chunk = index.get_chunks_for_document("doc-big")[0]
    small_chunk = index.get_chunks_for_document("doc-small")[0]
    manual_results = [
        KnowledgeSearchResult(chunk=big_chunk, title="Doc", score=0.9, rank=1, matched_terms=()),
        KnowledgeSearchResult(chunk=small_chunk, title="Doc", score=0.5, rank=2, matched_terms=()),
    ]
    context = ContextBuilder().build(
        manual_results, ContextBudget(max_chunks=5, max_total_chars=100)
    )
    assert len(context.chunks) == 1
    assert context.chunks[0].content == small_chunk.content  # whole chunk, not a truncated slice


def test_context_preserves_provenance() -> None:
    doc = _doc("doc-1", "reliability content here")
    index = _index(doc)
    results = search(index, KnowledgeSearchRequest(query="reliability"))
    context = ContextBuilder().build(results)
    assert context.chunks[0].provenance.document_id == "doc-1"
    assert context.chunks[0].provenance.source_id == "src-1"
    assert context.chunks[0].provenance.chunk_id == results[0].chunk.chunk_id
    assert context.chunks[0].provenance.rank == 1


def test_context_avoids_duplicate_chunk_ids() -> None:
    doc = _doc("doc-1", "reliability content here")
    index = _index(doc)
    results = search(index, KnowledgeSearchRequest(query="reliability"))
    duplicated_results = results + results  # simulate a caller passing the same result twice
    context = ContextBuilder().build(duplicated_results)
    assert len(context.chunks) == 1


def test_context_avoids_duplicate_content_across_different_chunk_ids() -> None:
    doc_a = _doc("doc-a", "reliability content here")
    doc_b = _doc("doc-b", "reliability content here")
    index = _index(doc_a, doc_b)
    results = search(index, KnowledgeSearchRequest(query="reliability"))
    assert len({r.chunk.chunk_id for r in results}) == 2  # genuinely different chunks
    context = ContextBuilder().build(results)
    assert len(context.chunks) == 1  # same content deduplicated


def test_context_selection_is_deterministic() -> None:
    docs = [_doc(f"doc-{i}", f"reliability topic {i}") for i in range(5)]
    index = _index(*docs)
    results = search(index, KnowledgeSearchRequest(query="reliability", limit=5))
    first = ContextBuilder().build(results)
    for _ in range(10):
        again = ContextBuilder().build(results)
        assert again == first


def test_context_from_empty_results_is_empty_and_not_truncated() -> None:
    context = ContextBuilder().build([])
    assert context.chunks == ()
    assert context.total_chars == 0
    assert context.truncated is False


def test_context_skips_oversized_chunk_but_still_fits_a_smaller_later_one() -> None:
    doc_a = _doc("doc-a", "reliability " * 200)  # too big to fit
    doc_b = _doc("doc-b", "reliability small")  # fits
    index = _index(doc_a, doc_b)
    results = search(index, KnowledgeSearchRequest(query="reliability"))
    context = ContextBuilder().build(results, ContextBudget(max_chunks=5, max_total_chars=50))
    assert any(c.content == "reliability small" for c in context.chunks)


def test_context_budget_rejects_non_positive_values() -> None:
    with pytest.raises(MalformedKnowledgeDataError):
        ContextBudget(max_chunks=0)
    with pytest.raises(MalformedKnowledgeDataError):
        ContextBudget(max_total_chars=0)


def test_context_builder_defensively_reorders_out_of_order_input() -> None:
    doc_a = _doc("doc-a", "reliability topic a")
    doc_b = _doc("doc-b", "reliability topic b")
    index = _index(doc_a, doc_b)
    results = search(index, KnowledgeSearchRequest(query="reliability"))
    reversed_results = list(reversed(results))
    context = ContextBuilder().build(reversed_results)
    ordinary_context = ContextBuilder().build(results)
    assert context == ordinary_context
