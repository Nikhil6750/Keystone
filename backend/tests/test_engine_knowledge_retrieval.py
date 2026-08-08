"""Tests for `app.engine.knowledge.retrieval.search` and
`app.engine.knowledge.ranking`: deterministic lexical relevance, filters,
limits, case normalization, and deterministic tie-breaking."""

from dataclasses import replace

import pytest

from app.engine.knowledge.chunking import chunk_document
from app.engine.knowledge.errors import MalformedKnowledgeDataError
from app.engine.knowledge.index import KnowledgeIndex
from app.engine.knowledge.models import KnowledgeDocument
from app.engine.knowledge.ranking import RankingWeights, extract_query_terms, score_chunk, tokenize
from app.engine.knowledge.retrieval import KnowledgeSearchRequest, search


def _doc(
    document_id: str, title: str, content: str, *, source_id: str = "src-1"
) -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id=document_id, source_id=source_id, title=title, content=content
    )


def _index(*docs: KnowledgeDocument) -> KnowledgeIndex:
    index = KnowledgeIndex()
    for doc in docs:
        index.upsert_document(doc, chunk_document(doc))
    return index


# --- tokenization / stopwords -----------------------------------------------------------------


def test_tokenize_is_case_normalized() -> None:
    assert tokenize("Router SCORING Reliability") == ["router", "scoring", "reliability"]


def test_extract_query_terms_removes_default_stopwords() -> None:
    terms = extract_query_terms("the router and the scorer")
    assert "the" not in terms
    assert "and" not in terms
    assert terms == {"router", "scorer"}


def test_extract_query_terms_empty_for_blank_query() -> None:
    assert extract_query_terms("   ") == set()


def test_extract_query_terms_empty_for_stopword_only_query() -> None:
    assert extract_query_terms("the a of") == set()


# --- exact / title / heading / content relevance ------------------------------------------------


def test_exact_term_match_in_content_scores_above_zero() -> None:
    index = _index(_doc("doc-1", "Notes", "The router selects agents based on reliability."))
    results = search(index, KnowledgeSearchRequest(query="reliability"))
    assert len(results) == 1
    assert results[0].score > 0.0
    assert "reliability" in results[0].matched_terms


def test_title_match_ranks_above_content_only_match() -> None:
    index = _index(
        _doc("doc-title", "Reliability Guide", "General notes about agents."),
        _doc("doc-content", "General Notes", "This document discusses reliability briefly."),
    )
    results = search(index, KnowledgeSearchRequest(query="reliability"))
    assert results[0].chunk.document_id == "doc-title"


def test_heading_match_boosts_score_over_plain_content_match() -> None:
    index = _index(
        _doc("doc-1", "Doc", "# Reliability\n\nSome unrelated body text about agents."),
    )
    chunks = index.all_chunks()
    heading_chunk = chunks[0]
    score, matched = score_chunk(
        heading_chunk,
        title="Doc",
        query="reliability",
        query_terms={"reliability"},
        weights=RankingWeights(),
    )
    assert score > 0.0
    assert matched == ("reliability",)


def test_content_relevance_scales_with_term_frequency_up_to_saturation() -> None:
    index = _index(
        _doc("doc-repeat", "Doc", "reliability reliability reliability reliability reliability"),
        _doc("doc-once", "Doc", "reliability mentioned once here"),
    )
    results = search(index, KnowledgeSearchRequest(query="reliability"))
    by_doc = {r.chunk.document_id: r.score for r in results}
    assert by_doc["doc-repeat"] > by_doc["doc-once"]


def test_case_normalization_matches_regardless_of_query_case() -> None:
    index = _index(_doc("doc-1", "Doc", "Reliability matters for routing."))
    lower = search(index, KnowledgeSearchRequest(query="reliability"))
    upper = search(index, KnowledgeSearchRequest(query="RELIABILITY"))
    mixed = search(index, KnowledgeSearchRequest(query="RelIabiliTy"))
    assert lower[0].score == upper[0].score == mixed[0].score


# --- multiple matches / limit ------------------------------------------------------------------


def test_multiple_matching_chunks_are_all_returned_up_to_limit() -> None:
    docs = [_doc(f"doc-{i}", "Doc", f"Reliability discussion number {i}.") for i in range(5)]
    index = _index(*docs)
    results = search(index, KnowledgeSearchRequest(query="reliability", limit=3))
    assert len(results) == 3
    assert [r.rank for r in results] == [1, 2, 3]


def test_limit_is_respected_even_with_many_more_matches() -> None:
    docs = [_doc(f"doc-{i}", "Doc", "Common term appears here.") for i in range(20)]
    index = _index(*docs)
    results = search(index, KnowledgeSearchRequest(query="common", limit=5))
    assert len(results) == 5


# --- filters ------------------------------------------------------------------------------------


def test_source_id_filter_restricts_results() -> None:
    index = _index(
        _doc("doc-a", "Doc", "shared term content", source_id="src-a"),
        _doc("doc-b", "Doc", "shared term content", source_id="src-b"),
    )
    results = search(index, KnowledgeSearchRequest(query="shared", source_ids=("src-a",)))
    assert {r.chunk.source_id for r in results} == {"src-a"}


def test_document_id_filter_restricts_results() -> None:
    index = _index(
        _doc("doc-a", "Doc", "shared term content"),
        _doc("doc-b", "Doc", "shared term content"),
    )
    results = search(index, KnowledgeSearchRequest(query="shared", document_ids=("doc-b",)))
    assert {r.chunk.document_id for r in results} == {"doc-b"}


def test_metadata_filter_restricts_results() -> None:
    index = KnowledgeIndex()
    doc = _doc("doc-1", "Doc", "shared term content")
    chunks = chunk_document(doc)
    tagged_chunk = replace(chunks[0], metadata={"category": "reference"})
    index.upsert_document(doc, [tagged_chunk])
    matches = search(
        index, KnowledgeSearchRequest(query="shared", metadata_filters={"category": "reference"})
    )
    no_matches = search(
        index, KnowledgeSearchRequest(query="shared", metadata_filters={"category": "other"})
    )
    assert len(matches) == 1
    assert no_matches == []


# --- no results / empty query -------------------------------------------------------------


def test_no_results_when_nothing_matches() -> None:
    index = _index(_doc("doc-1", "Doc", "Completely unrelated text."))
    results = search(index, KnowledgeSearchRequest(query="nonexistentword"))
    assert results == []


def test_empty_query_returns_no_results_not_all_documents() -> None:
    index = _index(_doc("doc-1", "Doc", "Some content here."))
    results = search(index, KnowledgeSearchRequest(query=""))
    assert results == []


def test_stopword_only_query_returns_no_results() -> None:
    index = _index(_doc("doc-1", "Doc", "Some content here."))
    results = search(index, KnowledgeSearchRequest(query="the and of"))
    assert results == []


def test_search_against_empty_index_returns_no_results() -> None:
    index = KnowledgeIndex()
    assert search(index, KnowledgeSearchRequest(query="anything")) == []


# --- deterministic tie-break ----------------------------------------------------------------------


def test_exact_tie_breaks_deterministically_by_chunk_id() -> None:
    docs = [
        _doc("doc-b", "Doc", "reliability content here"),
        _doc("doc-a", "Doc", "reliability content here"),
    ]
    index = _index(*docs)
    results = search(index, KnowledgeSearchRequest(query="reliability"))
    assert results[0].score == results[1].score
    assert [r.chunk.chunk_id for r in results] == sorted(r.chunk.chunk_id for r in results)


def test_search_ordering_is_stable_across_repeated_calls() -> None:
    docs = [
        _doc("doc-b", "Doc", "reliability content here"),
        _doc("doc-a", "Doc", "reliability content here"),
        _doc("doc-c", "Doc", "reliability different content"),
    ]
    index = _index(*docs)
    request = KnowledgeSearchRequest(query="reliability")
    first = [r.chunk.chunk_id for r in search(index, request)]
    for _ in range(10):
        assert [r.chunk.chunk_id for r in search(index, request)] == first


def test_ranking_weights_rejects_nan_or_inf() -> None:
    with pytest.raises(MalformedKnowledgeDataError):
        RankingWeights(content_term_frequency_weight=float("nan"))
    with pytest.raises(MalformedKnowledgeDataError):
        RankingWeights(title_match_weight=float("inf"))


def test_search_query_with_punctuation_only_returns_empty() -> None:
    index = _index(_doc("doc-1", "Doc", "Some content here."))
    assert search(index, KnowledgeSearchRequest(query="!!! ??? *** ###")) == []


def test_exact_phrase_bonus_boosts_score() -> None:
    index = _index(
        _doc("doc-phrase", "Doc", "the fast brown fox jumps over"),
        _doc("doc-split", "Doc", "brown fox fast jumps the over"),
    )
    results = search(index, KnowledgeSearchRequest(query="fast brown fox"))
    assert len(results) == 2
    assert results[0].chunk.document_id == "doc-phrase"
    assert results[0].score > results[1].score


def test_all_retrieval_scores_are_finite_and_in_unit_interval() -> None:
    docs = [
        _doc("doc-1", "Title Match", "reliability content with extra reliability reliability"),
        _doc("doc-2", "Heading", "# reliability\n\nreliability query terms"),
    ]
    index = _index(*docs)
    results = search(index, KnowledgeSearchRequest(query="reliability"))
    for res in results:
        assert 0.0 <= res.score <= 1.0
