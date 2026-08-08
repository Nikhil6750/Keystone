"""Tests for `app.engine.adaptive_retrieval.reranking.AdaptiveRetriever`:
static-mode equivalence to Stage 6A, learning-mode reranking, bounded
adjustment, deterministic tie-breaking, and `ContextBuilder` compatibility."""

from app.contracts.enums import AgentExecutionStatus
from app.contracts.verification import VerificationStatus
from app.engine.adaptive_retrieval.feedback import RetrievalFeedback
from app.engine.adaptive_retrieval.passport import rebuild_all_retrieval_passports
from app.engine.adaptive_retrieval.policy import AdaptiveRetrievalPolicy
from app.engine.adaptive_retrieval.reranking import AdaptiveRetriever, results_only
from app.engine.benchmark_learning.models import EvidenceSource
from app.engine.knowledge.chunking import chunk_document
from app.engine.knowledge.context import ContextBuilder
from app.engine.knowledge.index import KnowledgeIndex
from app.engine.knowledge.models import KnowledgeDocument
from app.engine.knowledge.retrieval import KnowledgeSearchRequest, search


def _doc(document_id: str, content: str, *, title: str = "Doc") -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id=document_id, source_id="src-1", title=title, content=content
    )


def _index(*docs: KnowledgeDocument) -> KnowledgeIndex:
    index = KnowledgeIndex()
    for doc in docs:
        index.upsert_document(doc, chunk_document(doc))
    return index


def _feedback_for(
    chunk_id: str,
    *,
    n: int,
    verification_status: VerificationStatus,
    task_type: str | None = "fix",
    repository_id: str | None = "org/repo",
) -> list[RetrievalFeedback]:
    return [
        RetrievalFeedback(
            retrieval_id=f"retrieval::{chunk_id}::sample-{i}",
            chunk_ids=(chunk_id,),
            verification_status=verification_status,
            task_type=task_type,
            repository_id=repository_id,
            execution_status=AgentExecutionStatus.SUCCEEDED,
            execution_id=f"execution-{chunk_id}-{i}",
        )
        for i in range(n)
    ]


# --- BASELINE: static mode == Stage 6A ordering -------------------------------------------


def test_adaptive_disabled_equals_stage6a_ordering() -> None:
    docs = [_doc(f"doc-{i}", f"reliability discussion {i}") for i in range(6)]
    index = _index(*docs)
    request = KnowledgeSearchRequest(query="reliability", limit=6)

    base = search(index, request)
    retriever = AdaptiveRetriever(policy=AdaptiveRetrievalPolicy(enabled=False))
    ranked = results_only(retriever.retrieve(index, request))

    assert [r.chunk.chunk_id for r in ranked] == [r.chunk.chunk_id for r in base]
    assert [r.score for r in ranked] == [r.score for r in base]
    assert [r.rank for r in ranked] == [r.rank for r in base]


def test_no_learning_evidence_equals_stage6a_ordering() -> None:
    """Adaptive enabled, but zero passports supplied -> still base order."""
    docs = [_doc(f"doc-{i}", f"reliability discussion {i}") for i in range(6)]
    index = _index(*docs)
    request = KnowledgeSearchRequest(query="reliability", limit=6)

    base = search(index, request)
    retriever = AdaptiveRetriever(policy=AdaptiveRetrievalPolicy(enabled=True))
    ranked = results_only(retriever.retrieve(index, request, task_type="fix"))

    assert [r.chunk.chunk_id for r in ranked] == [r.chunk.chunk_id for r in base]
    assert [r.score for r in ranked] == [r.score for r in base]


def test_disabled_policy_ignores_supplied_passports() -> None:
    """Even with real evidence available, a disabled policy must not use it."""
    doc = _doc("doc-1", "reliability alpha")
    index = _index(doc)
    request = KnowledgeSearchRequest(query="reliability")
    chunk = index.all_chunks()[0]

    feedback = _feedback_for(chunk.chunk_id, n=10, verification_status=VerificationStatus.PASSED)
    passports = rebuild_all_retrieval_passports(feedback)

    base = search(index, request)
    retriever = AdaptiveRetriever(policy=AdaptiveRetrievalPolicy(enabled=False))
    ranked = results_only(
        retriever.retrieve(
            index, request, task_type="fix", repository_id="org/repo",
            production_passports=passports,
        )
    )
    assert [r.score for r in ranked] == [r.score for r in base]


# --- LEARNING MODE: boosting/penalizing among similarly-relevant chunks --------------------


def test_strong_verified_history_can_boost_chunk_above_similar_relevance_peer() -> None:
    doc_a = _doc("doc-a", "reliability topic alpha", title="Doc")
    doc_b = _doc("doc-b", "reliability topic beta", title="Doc")
    index = _index(doc_a, doc_b)
    request = KnowledgeSearchRequest(query="reliability topic", limit=10)

    base = search(index, request)
    assert base[0].score == base[1].score  # similar base relevance, confirmed tied

    chunk_b = index.get_chunks_for_document("doc-b")[0]

    # chunk_b has a strong, sufficiently-sampled verified success history;
    # chunk_a has none.
    feedback = _feedback_for(chunk_b.chunk_id, n=6, verification_status=VerificationStatus.PASSED)
    passports = rebuild_all_retrieval_passports(feedback)

    retriever = AdaptiveRetriever(policy=AdaptiveRetrievalPolicy(enabled=True))
    ranked = retriever.retrieve(
        index, request, task_type="fix", repository_id="org/repo", production_passports=passports
    )
    assert ranked[0].result.chunk.chunk_id == chunk_b.chunk_id
    assert ranked[0].adjustment > 0.0


def test_repeated_verified_failure_can_penalize_chunk() -> None:
    doc_a = _doc("doc-a", "reliability topic alpha")
    doc_b = _doc("doc-b", "reliability topic beta")
    index = _index(doc_a, doc_b)
    request = KnowledgeSearchRequest(query="reliability topic", limit=10)

    chunk_a = index.get_chunks_for_document("doc-a")[0]
    chunk_b = index.get_chunks_for_document("doc-b")[0]

    feedback = _feedback_for(chunk_a.chunk_id, n=6, verification_status=VerificationStatus.FAILED)
    passports = rebuild_all_retrieval_passports(feedback)

    retriever = AdaptiveRetriever(policy=AdaptiveRetrievalPolicy(enabled=True))
    ranked = retriever.retrieve(
        index, request, task_type="fix", repository_id="org/repo", production_passports=passports
    )
    a_result = next(r for r in ranked if r.result.chunk.chunk_id == chunk_a.chunk_id)
    b_result = next(r for r in ranked if r.result.chunk.chunk_id == chunk_b.chunk_id)
    assert a_result.adjustment < 0.0
    assert b_result.adjustment == 0.0
    assert ranked[0].result.chunk.chunk_id == chunk_b.chunk_id  # b now ranks above penalized a


def test_thin_evidence_below_minimum_sample_does_not_change_ranking() -> None:
    doc_a = _doc("doc-a", "reliability topic alpha")
    doc_b = _doc("doc-b", "reliability topic beta")
    index = _index(doc_a, doc_b)
    request = KnowledgeSearchRequest(query="reliability topic", limit=10)

    chunk_b = index.get_chunks_for_document("doc-b")[0]
    base = search(index, request)

    # Only 2 samples -- below MIN_SAMPLE_SIZE_FOR_CONFIDENCE (5).
    feedback = _feedback_for(chunk_b.chunk_id, n=2, verification_status=VerificationStatus.PASSED)
    passports = rebuild_all_retrieval_passports(feedback)

    retriever = AdaptiveRetriever(policy=AdaptiveRetrievalPolicy(enabled=True))
    ranked = retriever.retrieve(
        index, request, task_type="fix", repository_id="org/repo", production_passports=passports
    )
    assert [r.result.score for r in ranked] == [r.score for r in base]
    assert all(r.adjustment == 0.0 for r in ranked)


def test_adjustment_is_bounded_even_with_perfect_history() -> None:
    doc = _doc("doc-1", "reliability alpha")
    index = _index(doc)
    request = KnowledgeSearchRequest(query="reliability")
    chunk = index.all_chunks()[0]

    feedback = _feedback_for(chunk.chunk_id, n=50, verification_status=VerificationStatus.PASSED)
    passports = rebuild_all_retrieval_passports(feedback)

    policy = AdaptiveRetrievalPolicy(enabled=True, max_positive_adjustment=0.15)
    retriever = AdaptiveRetriever(policy=policy)
    ranked = retriever.retrieve(
        index, request, task_type="fix", repository_id="org/repo", production_passports=passports
    )
    assert ranked[0].adjustment == 0.15  # exactly the bound, never more
    assert ranked[0].result.score <= 1.0


def test_adjustment_bounded_even_with_total_failure_history() -> None:
    doc = _doc("doc-1", "reliability alpha")
    index = _index(doc)
    request = KnowledgeSearchRequest(query="reliability")
    chunk = index.all_chunks()[0]

    feedback = _feedback_for(chunk.chunk_id, n=50, verification_status=VerificationStatus.FAILED)
    passports = rebuild_all_retrieval_passports(feedback)

    policy = AdaptiveRetrievalPolicy(enabled=True, max_negative_adjustment=0.15)
    retriever = AdaptiveRetriever(policy=policy)
    ranked = retriever.retrieve(
        index, request, task_type="fix", repository_id="org/repo", production_passports=passports
    )
    assert ranked[0].adjustment == -0.15
    assert ranked[0].result.score >= 0.0


def test_no_score_explosion_final_score_always_bounded() -> None:
    doc = _doc("doc-1", "reliability alpha")
    index = _index(doc)
    request = KnowledgeSearchRequest(query="reliability")
    chunk = index.all_chunks()[0]

    feedback = _feedback_for(chunk.chunk_id, n=50, verification_status=VerificationStatus.PASSED)
    passports = rebuild_all_retrieval_passports(feedback)
    # deliberately oversized bound -- final_score clamping must still hold
    policy = AdaptiveRetrievalPolicy(enabled=True, max_positive_adjustment=5.0)
    retriever = AdaptiveRetriever(policy=policy)
    ranked = retriever.retrieve(
        index, request, task_type="fix", repository_id="org/repo", production_passports=passports
    )
    assert 0.0 <= ranked[0].result.score <= 1.0


# --- deterministic ties -----------------------------------------------------------------------


def test_ties_after_adjustment_break_by_chunk_id_deterministically() -> None:
    docs = [_doc(f"doc-{i}", "reliability topic here") for i in range(4)]
    index = _index(*docs)
    request = KnowledgeSearchRequest(query="reliability topic", limit=10)
    retriever = AdaptiveRetriever(policy=AdaptiveRetrievalPolicy(enabled=True))

    def _ordered_chunk_ids() -> list[str]:
        ranked = retriever.retrieve(index, request, task_type="fix")
        return [r.chunk.chunk_id for r in results_only(ranked)]

    first = _ordered_chunk_ids()
    for _ in range(10):
        assert _ordered_chunk_ids() == first
    assert first == sorted(first)  # tie-break is ascending chunk_id, same as Stage 6A


# --- ContextBuilder integration --------------------------------------------------------------


def test_adaptive_output_compatible_with_context_builder() -> None:
    docs = [_doc(f"doc-{i}", f"reliability discussion {i}") for i in range(5)]
    index = _index(*docs)
    request = KnowledgeSearchRequest(query="reliability", limit=5)
    chunk_ids = [c.chunk_id for c in index.all_chunks()]

    feedback = _feedback_for(
        chunk_ids[0], n=6, verification_status=VerificationStatus.PASSED
    )
    passports = rebuild_all_retrieval_passports(feedback)
    retriever = AdaptiveRetriever(policy=AdaptiveRetrievalPolicy(enabled=True))
    ranked = retriever.retrieve(
        index, request, task_type="fix", repository_id="org/repo", production_passports=passports
    )

    context = ContextBuilder().build(results_only(ranked))
    assert len(context.chunks) > 0
    assert context.chunks[0].provenance.chunk_id == chunk_ids[0]  # boosted chunk ranks first


# --- adversarial: benchmark/production evidence never blended -------------------------------


def test_production_evidence_used_over_benchmark_when_both_sufficient() -> None:
    """Production always wins when it independently clears the sample
    gate, even if benchmark evidence for the same chunk points the other
    way -- never averaged, never blended."""
    doc = _doc("doc-1", "reliability alpha")
    index = _index(doc)
    request = KnowledgeSearchRequest(query="reliability")
    chunk = index.all_chunks()[0]

    production_feedback = [
        RetrievalFeedback(
            retrieval_id=f"retrieval::prod-{i}",
            chunk_ids=(chunk.chunk_id,),
            verification_status=VerificationStatus.PASSED,
            task_type="fix",
            repository_id="org/repo",
            execution_status=AgentExecutionStatus.SUCCEEDED,
            evidence_source=EvidenceSource.PRODUCTION,
            execution_id=f"execution-prod-{i}",
        )
        for i in range(6)
    ]
    benchmark_feedback = [
        RetrievalFeedback(
            retrieval_id=f"retrieval::bench-{i}",
            chunk_ids=(chunk.chunk_id,),
            verification_status=VerificationStatus.FAILED,  # opposite signal
            task_type="fix",
            repository_id="org/repo",
            execution_status=AgentExecutionStatus.SUCCEEDED,
            evidence_source=EvidenceSource.BENCHMARK,
            campaign_id="campaign-1",
        )
        for i in range(6)
    ]
    production_passports = rebuild_all_retrieval_passports(production_feedback)
    benchmark_passports = rebuild_all_retrieval_passports(benchmark_feedback)

    policy = AdaptiveRetrievalPolicy(enabled=True, allow_benchmark_evidence=True)
    retriever = AdaptiveRetriever(policy=policy)
    ranked = retriever.retrieve(
        index, request, task_type="fix", repository_id="org/repo",
        production_passports=production_passports, benchmark_passports=benchmark_passports,
    )
    assert ranked[0].evidence.source == "production"
    # reflects production's PASSED history, not benchmark's opposite FAILED signal
    assert ranked[0].adjustment > 0.0


def test_benchmark_evidence_only_used_as_fallback_never_blended() -> None:
    doc = _doc("doc-1", "reliability alpha")
    index = _index(doc)
    request = KnowledgeSearchRequest(query="reliability")
    chunk = index.all_chunks()[0]

    # No production evidence at all -- only benchmark.
    benchmark_feedback = [
        RetrievalFeedback(
            retrieval_id=f"retrieval::bench-{i}",
            chunk_ids=(chunk.chunk_id,),
            verification_status=VerificationStatus.PASSED,
            task_type="fix",
            repository_id="org/repo",
            execution_status=AgentExecutionStatus.SUCCEEDED,
            evidence_source=EvidenceSource.BENCHMARK,
            campaign_id="campaign-1",
        )
        for i in range(6)
    ]
    benchmark_passports = rebuild_all_retrieval_passports(benchmark_feedback)

    policy = AdaptiveRetrievalPolicy(enabled=True, allow_benchmark_evidence=True)
    retriever = AdaptiveRetriever(policy=policy)
    ranked = retriever.retrieve(
        index, request, task_type="fix", repository_id="org/repo",
        benchmark_passports=benchmark_passports,
    )
    assert ranked[0].evidence.source == "benchmark"
    assert ranked[0].adjustment > 0.0


def test_benchmark_evidence_ignored_when_policy_disallows_it() -> None:
    doc = _doc("doc-1", "reliability alpha")
    index = _index(doc)
    request = KnowledgeSearchRequest(query="reliability")
    chunk = index.all_chunks()[0]

    benchmark_feedback = [
        RetrievalFeedback(
            retrieval_id=f"retrieval::bench-{i}",
            chunk_ids=(chunk.chunk_id,),
            verification_status=VerificationStatus.PASSED,
            task_type="fix",
            repository_id="org/repo",
            execution_status=AgentExecutionStatus.SUCCEEDED,
            evidence_source=EvidenceSource.BENCHMARK,
            campaign_id="campaign-1",
        )
        for i in range(6)
    ]
    benchmark_passports = rebuild_all_retrieval_passports(benchmark_feedback)

    policy = AdaptiveRetrievalPolicy(enabled=True, allow_benchmark_evidence=False)
    retriever = AdaptiveRetriever(policy=policy)
    ranked = retriever.retrieve(
        index, request, task_type="fix", repository_id="org/repo",
        benchmark_passports=benchmark_passports,
    )
    assert ranked[0].evidence.source == "none"
    assert ranked[0].adjustment == 0.0


def test_context_builder_provenance_preserved_through_adaptive_reranking() -> None:
    doc = _doc("doc-1", "reliability alpha content")
    index = _index(doc)
    request = KnowledgeSearchRequest(query="reliability")
    retriever = AdaptiveRetriever(policy=AdaptiveRetrievalPolicy(enabled=False))
    ranked = retriever.retrieve(index, request)
    context = ContextBuilder().build(results_only(ranked))
    assert context.chunks[0].provenance.source_id == "src-1"
    assert context.chunks[0].provenance.document_id == "doc-1"


def test_context_budget_still_respected_after_adaptive_reranking() -> None:
    docs = [_doc(f"doc-{i}", f"reliability discussion {i}") for i in range(10)]
    index = _index(*docs)
    request = KnowledgeSearchRequest(query="reliability", limit=10)
    retriever = AdaptiveRetriever(policy=AdaptiveRetrievalPolicy(enabled=False))
    ranked = retriever.retrieve(index, request)

    from app.engine.knowledge.context import ContextBudget

    context = ContextBuilder().build(results_only(ranked), ContextBudget(max_chunks=3))
    assert len(context.chunks) == 3
