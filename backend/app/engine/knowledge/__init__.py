"""Stage 6A: Provider-Neutral Knowledge Engine Core.

Architecture:

    Knowledge Source -> Knowledge Documents -> Knowledge Chunks ->
    Knowledge Index -> Search / Retrieval -> Ranking -> Context Builder ->
    (future) Planner / Orchestrator / Agents

`source.py` defines `KnowledgeSource`, a structural Protocol future
adapters (Obsidian, a repository, a documentation site, execution history)
implement -- Stage 6A itself provides only `InMemoryKnowledgeSource`, no
filesystem access. `models.py` defines the provider-neutral
`KnowledgeDocument`/`KnowledgeChunk`/`KnowledgeProvenance` value types --
deliberately distinct from `app.contracts.knowledge`'s Obsidian-vault-
shaped contracts, which this package does not import, extend, or modify.
`chunking.py` deterministically splits a document into chunks along
heading/paragraph boundaries with a bounded fallback split; the same
document and policy always produce the same chunks. `index.py` is an
in-memory `KnowledgeIndex` whose single `upsert_document` entry point
makes stale-chunk cleanup on update structurally guaranteed, not merely
tested for. `ranking.py`/`retrieval.py` implement deterministic lexical
(term-overlap) search with an explicit, documented stopword list and
weighted scoring formula -- no embeddings, no model calls. `context.py`'s
`ContextBuilder` turns ranked results into a budget-respecting,
deduplicated, provenance-preserving `ContextResult` -- structured data
only, never a formatted prompt.

Does not implement an Obsidian adapter, embeddings, a vector database,
self-learning/adaptive retrieval, Nemotron integration, the Benchmark
Engine, any Stage 7+ work, APIs, VS Code integration, persistence/database
migrations, or any external model call -- and does not modify
`app.contracts`, `app.engine.routing`, `app.engine.learning`,
`app.engine.verification`, `app.engine.planning`, `app.engine.workflow`,
or `app.engine.explainability`.
"""

from app.engine.knowledge.chunking import ChunkingPolicy, chunk_document, compute_chunk_id
from app.engine.knowledge.context import ContextBudget, ContextBuilder, ContextChunk, ContextResult
from app.engine.knowledge.errors import (
    KnowledgeEngineError,
    MalformedKnowledgeDataError,
    UnsafeKnowledgeDataError,
)
from app.engine.knowledge.index import IndexStats, KnowledgeIndex
from app.engine.knowledge.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeProvenance,
    looks_like_unsafe_local_path,
    validate_safe_metadata,
)
from app.engine.knowledge.ranking import (
    DEFAULT_STOPWORDS,
    RankingWeights,
    extract_query_terms,
    score_chunk,
    tokenize,
)
from app.engine.knowledge.retrieval import KnowledgeSearchRequest, KnowledgeSearchResult, search
from app.engine.knowledge.source import InMemoryKnowledgeSource, KnowledgeSource

__all__ = [
    "DEFAULT_STOPWORDS",
    "ChunkingPolicy",
    "ContextBudget",
    "ContextBuilder",
    "ContextChunk",
    "ContextResult",
    "InMemoryKnowledgeSource",
    "IndexStats",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "KnowledgeEngineError",
    "KnowledgeIndex",
    "KnowledgeProvenance",
    "KnowledgeSearchRequest",
    "KnowledgeSearchResult",
    "KnowledgeSource",
    "MalformedKnowledgeDataError",
    "RankingWeights",
    "UnsafeKnowledgeDataError",
    "chunk_document",
    "compute_chunk_id",
    "extract_query_terms",
    "looks_like_unsafe_local_path",
    "score_chunk",
    "search",
    "tokenize",
    "validate_safe_metadata",
]
