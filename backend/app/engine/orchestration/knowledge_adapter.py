"""Phase A (Knowledge preparation) glue.

The Stage 6 `KnowledgeIndex` candidate set remains authoritative
throughout the pipeline: Stage 7.5 adaptive reranking
(`AdaptiveRetriever.retrieve`) only re-scores/re-sorts what `search()`
already returned (see its own module docstring -- it never adds a
candidate), and `ContextBuilder` only ever selects a bounded, deduplicated
subset of that same set. This module adds no retrieval logic of its own;
it exists purely to bridge two real gaps discovery confirmed:

1. **Two distinct `KnowledgeSearchResult` types.** Stage 6A's own
   dataclass (`app.engine.knowledge.retrieval.KnowledgeSearchResult`) is
   not the Obsidian-vault-shaped Pydantic model `ManagerRequest`/
   `PlanningRequest` accept (`app.contracts.knowledge.KnowledgeSearchResult`).
   `build_manager_knowledge_context` converts a `ContextBuilder`-selected
   `ContextResult` into the latter, looking up each chunk's document title
   from the same `KnowledgeIndex` (the only source of truth for it --
   `ContextChunk`/`KnowledgeProvenance` do not carry a title field).
2. **No production caller built a `RetrievalObservation` before.**
   `build_retrieval_observation` does, from the same base `search()`
   results and `ContextBuilder`-selected subset Phase A already computed,
   so Phase G (retrieval feedback) can reference the identical,
   deterministically-computed `retrieval_id` later without re-deriving it
   differently.
"""

from app.contracts.knowledge import KnowledgeSearchResult as ContractKnowledgeSearchResult
from app.engine.adaptive_retrieval.models import RetrievalObservation, compute_query_fingerprint
from app.engine.knowledge.context import ContextResult
from app.engine.knowledge.index import KnowledgeIndex
from app.engine.knowledge.retrieval import KnowledgeSearchResult


def build_manager_knowledge_context(
    index: KnowledgeIndex, context_result: ContextResult
) -> list[ContractKnowledgeSearchResult]:
    """Convert a `ContextBuilder`-selected `ContextResult` into the bounded
    `app.contracts.knowledge.KnowledgeSearchResult` list `ManagerRequest`/
    `PlanningRequest` accept. `ManagerRequest`'s own field validator
    (`app.engine.manager.models.MAX_KNOWLEDGE_CONTEXT_ITEMS`) bounds the
    final count when this is passed into `build_manager_request`
    (`app.engine.manager.context`) -- this function never truncates on its
    own, it only converts."""
    converted: list[ContractKnowledgeSearchResult] = []
    for chunk in context_result.chunks:
        document = index.get_document(chunk.provenance.document_id)
        title = document.title if document is not None else chunk.provenance.document_id
        converted.append(
            ContractKnowledgeSearchResult(
                document_id=chunk.provenance.document_id,
                vault_id=chunk.provenance.source_id,
                title=title,
                snippet=chunk.content,
                score=chunk.provenance.score if chunk.provenance.score is not None else 0.0,
            )
        )
    return converted


def build_retrieval_observation(
    *,
    query: str,
    task_type: str | None,
    repository_id: str | None,
    agent_type: str | None,
    base_results: list[KnowledgeSearchResult],
    context_result: ContextResult,
) -> RetrievalObservation | None:
    """One `RetrievalObservation` covering everything base retrieval
    (`base_results`, Stage 6A's own order) returned versus what
    `ContextBuilder` actually selected (`context_result`). Returns `None`
    if `base_results` is empty -- there is nothing to observe, and
    `RetrievalObservation` itself rejects an empty `query_fingerprint`
    derived from an empty search, so this is checked here rather than
    letting that construction fail unclearly downstream."""
    if not base_results:
        return None
    selected_chunk_ids = {chunk.provenance.chunk_id for chunk in context_result.chunks}
    return RetrievalObservation(
        query_fingerprint=compute_query_fingerprint(query),
        task_type=task_type,
        repository_id=repository_id,
        agent_type=agent_type,
        retrieved_chunk_ids=tuple(result.chunk.chunk_id for result in base_results),
        retrieved_chunk_content_hashes=tuple(result.chunk.content_hash for result in base_results),
        original_ranks=tuple(result.rank for result in base_results),
        original_scores=tuple(result.score for result in base_results),
        selected_chunk_ids=tuple(
            result.chunk.chunk_id
            for result in base_results
            if result.chunk.chunk_id in selected_chunk_ids
        ),
    )


__all__ = ["build_manager_knowledge_context", "build_retrieval_observation"]
