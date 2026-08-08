"""`KnowledgeSearchRequest`/`KnowledgeSearchResult` and the `search()`
entry point tying `KnowledgeIndex` (storage) and `ranking.py` (scoring)
together into deterministic lexical retrieval.

**Deterministic ranking, always.** Results are sorted by `(-score,
chunk_id)` -- descending score, then ascending `chunk_id` as the final,
unambiguous tie-break (mirroring Stage 4B's own `Router._ranking_key`
convention: a deterministic tie-break is never evidence of one chunk being
"better," only a documented, stable ordering rule). The same index state
plus the same request always produces the same ordered result list.

**No hidden reasoning.** Every field on `KnowledgeSearchResult` is directly
derived from observable data already on the matched `KnowledgeChunk`/its
document: the matched query terms, the bounded lexical score, the rank,
and (`.provenance`) exactly which source/document/chunk produced the hit.
"""

from dataclasses import dataclass, field

from app.engine.knowledge.errors import MalformedKnowledgeDataError
from app.engine.knowledge.index import KnowledgeIndex
from app.engine.knowledge.models import KnowledgeChunk, KnowledgeProvenance, validate_safe_metadata
from app.engine.knowledge.ranking import RankingWeights, extract_query_terms, score_chunk


@dataclass(frozen=True)
class KnowledgeSearchRequest:
    """One search request against a `KnowledgeIndex`.

    `metadata_filters`, when given, is an exact-match `key == value`
    conjunction only (never a query language, never unbounded) -- and is
    itself validated by the same `validate_safe_metadata` every
    document/chunk metadata dict is validated by, so a filter can never
    smuggle in a reasoning-shaped or credential-shaped key either.
    """

    query: str
    limit: int = 10
    source_ids: tuple[str, ...] | None = None
    document_ids: tuple[str, ...] | None = None
    metadata_filters: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if self.limit <= 0:
            raise MalformedKnowledgeDataError("limit must be positive")
        if self.metadata_filters:
            validate_safe_metadata(self.metadata_filters)


@dataclass(frozen=True)
class KnowledgeSearchResult:
    """One ranked search hit."""

    chunk: KnowledgeChunk
    title: str
    score: float
    rank: int
    matched_terms: tuple[str, ...] = field(default_factory=tuple)

    @property
    def provenance(self) -> KnowledgeProvenance:
        """Where this hit came from -- always answerable, never hidden."""
        return KnowledgeProvenance(
            source_id=self.chunk.source_id,
            document_id=self.chunk.document_id,
            chunk_id=self.chunk.chunk_id,
            heading_path=self.chunk.heading_path,
            rank=self.rank,
            score=self.score,
        )


def search(
    index: KnowledgeIndex,
    request: KnowledgeSearchRequest,
    *,
    weights: RankingWeights | None = None,
) -> list[KnowledgeSearchResult]:
    """Deterministic lexical search: filter -> score -> rank -> limit.
    An empty/stopword-only query returns `[]` cleanly (never an error, never
    "all documents")."""
    weights = weights or RankingWeights()
    query_terms = extract_query_terms(request.query)
    if not query_terms:
        return []

    candidates = index.all_chunks()

    if request.source_ids is not None:
        allowed_sources = set(request.source_ids)
        candidates = [chunk for chunk in candidates if chunk.source_id in allowed_sources]
    if request.document_ids is not None:
        allowed_documents = set(request.document_ids)
        candidates = [chunk for chunk in candidates if chunk.document_id in allowed_documents]
    if request.metadata_filters:
        metadata_filters = request.metadata_filters
        candidates = [
            chunk
            for chunk in candidates
            if all(chunk.metadata.get(key) == value for key, value in metadata_filters.items())
        ]

    scored: list[tuple[KnowledgeChunk, str, float, tuple[str, ...]]] = []
    for chunk in candidates:
        document = index.get_document(chunk.document_id)
        title = document.title if document is not None else ""
        chunk_score, matched_terms = score_chunk(
            chunk, title=title, query=request.query, query_terms=query_terms, weights=weights
        )
        if chunk_score <= 0.0:
            continue
        scored.append((chunk, title, chunk_score, matched_terms))

    scored.sort(key=lambda item: (-item[2], item[0].chunk_id))

    limited = scored[: request.limit]
    results = [
        KnowledgeSearchResult(
            chunk=chunk, title=title, score=chunk_score, rank=rank, matched_terms=matched_terms
        )
        for rank, (chunk, title, chunk_score, matched_terms) in enumerate(limited, start=1)
    ]
    return results


__all__ = ["KnowledgeSearchRequest", "KnowledgeSearchResult", "search"]
