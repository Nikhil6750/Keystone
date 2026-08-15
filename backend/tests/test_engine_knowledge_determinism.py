"""Cross-cutting DETERMINISM tests for the Stage 6A knowledge engine:
shuffled document insertion order, repeated identical searches, and
"same index + same query => identical semantic results" end to end."""

import random

from app.engine.knowledge.chunking import chunk_document
from app.engine.knowledge.context import ContextBuilder
from app.engine.knowledge.index import KnowledgeIndex
from app.engine.knowledge.models import KnowledgeDocument
from app.engine.knowledge.retrieval import KnowledgeSearchRequest, search


def _doc(document_id: str, content: str, *, source_id: str = "src-1") -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id=document_id, source_id=source_id, title="Doc", content=content
    )


def _build_index(docs: list[KnowledgeDocument]) -> KnowledgeIndex:
    index = KnowledgeIndex()
    for doc in docs:
        index.upsert_document(doc, chunk_document(doc))
    return index


def test_shuffled_document_insertion_order_produces_identical_index_state() -> None:
    docs = [_doc(f"doc-{i}", f"reliability topic number {i}") for i in range(8)]
    shuffled = list(docs)
    random.Random(11).shuffle(shuffled)

    forward_index = _build_index(docs)
    shuffled_index = _build_index(shuffled)

    assert forward_index.list_documents() == shuffled_index.list_documents()
    assert forward_index.all_chunks() == shuffled_index.all_chunks()


def test_shuffled_document_insertion_order_produces_identical_search_results() -> None:
    docs = [_doc(f"doc-{i}", f"reliability topic number {i}") for i in range(8)]
    shuffled = list(docs)
    random.Random(23).shuffle(shuffled)

    forward_index = _build_index(docs)
    shuffled_index = _build_index(shuffled)

    request = KnowledgeSearchRequest(query="reliability", limit=8)
    forward_results = [(r.chunk.chunk_id, r.score, r.rank) for r in search(forward_index, request)]
    shuffled_results = [
        (r.chunk.chunk_id, r.score, r.rank) for r in search(shuffled_index, request)
    ]
    assert forward_results == shuffled_results


def test_repeated_identical_search_twenty_times_is_stable() -> None:
    docs = [_doc(f"doc-{i}", f"router scoring reliability {i}") for i in range(6)]
    index = _build_index(docs)
    request = KnowledgeSearchRequest(query="router scoring", limit=6)

    first = [(r.chunk.chunk_id, r.score, r.matched_terms) for r in search(index, request)]
    for _ in range(20):
        again = [(r.chunk.chunk_id, r.score, r.matched_terms) for r in search(index, request)]
        assert again == first


def test_same_index_and_query_produce_identical_end_to_end_context() -> None:
    docs = [
        _doc(f"doc-{i}", f"# Heading {i}\n\nRouter reliability discussion {i}.") for i in range(5)
    ]
    index = _build_index(docs)
    request = KnowledgeSearchRequest(query="router reliability", limit=5)

    def run_pipeline() -> tuple[tuple[str, ...], int, bool]:
        results = search(index, request)
        context = ContextBuilder().build(results)
        return (
            tuple(c.provenance.chunk_id for c in context.chunks),
            context.total_chars,
            context.truncated,
        )

    first = run_pipeline()
    for _ in range(10):
        assert run_pipeline() == first


def test_exact_tie_ordering_is_strictly_deterministic_by_chunk_id() -> None:
    docs = [_doc(f"doc-{i}", "identical query matching content") for i in (3, 1, 4, 2, 0)]
    index = _build_index(docs)
    request = KnowledgeSearchRequest(query="matching", limit=5)
    results = search(index, request)
    chunk_ids = [r.chunk.chunk_id for r in results]
    assert chunk_ids == sorted(chunk_ids)


def test_update_and_reindex_determinism() -> None:
    initial_docs = [
        _doc("doc-1", "Original para 1.\n\nOriginal para 2."),
        _doc("doc-2", "Doc 2 content."),
    ]
    index = _build_index(initial_docs)

    updated_doc_1 = _doc("doc-1", "Updated para 1.\n\nUpdated para 2.\n\nUpdated para 3.")
    index.upsert_document(updated_doc_1, chunk_document(updated_doc_1))

    fresh_docs = [updated_doc_1, initial_docs[1]]
    fresh_index = _build_index(fresh_docs)

    assert index.list_documents() == fresh_index.list_documents()
    assert index.all_chunks() == fresh_index.all_chunks()

    req = KnowledgeSearchRequest(query="updated")
    assert search(index, req) == search(fresh_index, req)
