"""`AdaptiveRetriever`: Stage 7.5's wrapper around Stage 6A's base
retrieval -- never a replacement for it.

    KnowledgeIndex + KnowledgeSearchRequest
            |
            v
    app.engine.knowledge.retrieval.search()   <- Stage 6A, unmodified, authoritative
            |
            v
    list[KnowledgeSearchResult]                 (candidate set -- already
            |                                     filtered/scored/limited
            |                                     by Stage 6A's own rules)
            v
    AdaptiveRetriever.retrieve()                (this module)
            |
            v
    list[KnowledgeSearchResult]                 (same chunks, re-scored,
                                                   re-ranked, re-numbered --
                                                   directly ContextBuilder-
                                                   compatible)

**Stage 6A eligibility can never be bypassed.** This module calls Stage
6A's own `search()` to get its candidate list and *never* adds, removes,
or substitutes a chunk -- it only re-scores and re-sorts the exact set
`search()` already decided was eligible (document availability, source
restrictions, `limit`, metadata filters: all already applied by the time
this module sees the results). There is no code path here that looks up
an arbitrary `KnowledgeChunk` by id outside that returned set.

**Static mode is structural, not incidental.** When `policy.enabled` is
`False`, or a chunk has no sufficient evidence, its adjustment is exactly
`0.0` -- `final_score = clamp(base_score + 0.0) == base_score` for every
result, so re-sorting by the same `(-score, chunk_id)` key Stage 6A itself
uses reproduces Stage 6A's own order byte-for-byte. This isn't a special
"disabled" code branch that could drift from the "enabled" branch over
time; it falls out of the same scoring path always running, just with a
provably-zero adjustment.

**Stale evidence is never trusted, in two layers.** Primarily, structurally:
Stage 6A's own `chunk_id` already embeds a content-hash prefix
(`app.engine.knowledge.chunking.compute_chunk_id`), so a chunk whose
content changed gets a genuinely different `chunk_id` -- a
`production_passports`/`benchmark_passports` lookup by `chunk.chunk_id`
for changed content simply finds nothing, with no code required here at
all. Secondarily, defense-in-depth: `passport.py`'s `rebuild_*` functions
accept the *current* content hash per chunk and drop any feedback whose
recorded hash disagrees, so even a passport built and reused across a
content change (or a hypothetical future `chunk_id` scheme that doesn't
embed the hash) still can't apply stale evidence. This module trusts
whatever `RetrievalPassport`s it is given -- staleness is filtered before
they reach here, once per index update, not re-checked per query.

**No hidden global state.** `production_passports`/`benchmark_passports`
are plain, caller-supplied `dict[str, RetrievalPassport]` arguments -- not
a module-level registry, not fetched from a database, not read from any
process-wide singleton. A caller who wants adaptive re-ranking must
explicitly build and pass in the evidence.
"""

import dataclasses
from dataclasses import dataclass

from app.engine.adaptive_retrieval.passport import RetrievalPassport
from app.engine.adaptive_retrieval.policy import AdaptiveRetrievalPolicy
from app.engine.adaptive_retrieval.scoring import (
    SelectedEvidence,
    bounded_adjustment,
    select_evidence,
)
from app.engine.knowledge.index import KnowledgeIndex
from app.engine.knowledge.retrieval import KnowledgeSearchRequest, KnowledgeSearchResult, search


@dataclass(frozen=True)
class RankedResult:
    """One re-ranked result: the `KnowledgeSearchResult` itself (directly
    `ContextBuilder`-compatible) plus which evidence, if any, adjusted it --
    fully explainable, never a hidden reason for a rank change."""

    result: KnowledgeSearchResult
    base_score: float
    adjustment: float
    evidence: SelectedEvidence


class AdaptiveRetriever:
    """Wraps Stage 6A `search()` with optional, conservative, deterministic
    adaptive re-ranking. Stateless beyond its configured `AdaptiveRetrievalPolicy`
    -- every call to `retrieve` is a pure function of its arguments."""

    def __init__(self, *, policy: AdaptiveRetrievalPolicy | None = None) -> None:
        self._policy = policy or AdaptiveRetrievalPolicy()

    def retrieve(
        self,
        index: KnowledgeIndex,
        request: KnowledgeSearchRequest,
        *,
        task_type: str | None = None,
        repository_id: str | None = None,
        production_passports: dict[str, RetrievalPassport] | None = None,
        benchmark_passports: dict[str, RetrievalPassport] | None = None,
    ) -> list[RankedResult]:
        """Run Stage 6A's base retrieval, then (only if `self._policy.enabled`)
        conservatively re-score and re-sort the returned candidates.
        `production_passports`/`benchmark_passports` are keyed by `chunk_id`;
        both default to empty (no evidence -> no adjustment -> base order)."""
        base_results = search(index, request)
        production_passports = production_passports or {}
        benchmark_passports = benchmark_passports or {}

        ranked: list[RankedResult] = []
        for base_result in base_results:
            chunk = base_result.chunk
            evidence = self._select_evidence_for_chunk(
                production_passport=production_passports.get(chunk.chunk_id),
                benchmark_passport=benchmark_passports.get(chunk.chunk_id),
                task_type=task_type,
                repository_id=repository_id,
            )
            adjustment = bounded_adjustment(evidence, policy=self._policy)
            final_score = max(0.0, min(1.0, base_result.score + adjustment))
            ranked.append(
                RankedResult(
                    result=dataclasses.replace(base_result, score=final_score),
                    base_score=base_result.score,
                    adjustment=adjustment,
                    evidence=evidence,
                )
            )

        ranked.sort(key=lambda item: (-item.result.score, item.result.chunk.chunk_id))

        renumbered: list[RankedResult] = []
        for rank, item in enumerate(ranked, start=1):
            renumbered.append(
                dataclasses.replace(item, result=dataclasses.replace(item.result, rank=rank))
            )
        return renumbered

    def _select_evidence_for_chunk(
        self,
        *,
        production_passport: RetrievalPassport | None,
        benchmark_passport: RetrievalPassport | None,
        task_type: str | None,
        repository_id: str | None,
    ) -> SelectedEvidence:
        if not self._policy.enabled:
            return SelectedEvidence(source="none", tier="none", bucket=None)
        return select_evidence(
            production_passport=production_passport,
            benchmark_passport=benchmark_passport,
            task_type=task_type,
            repository_id=repository_id,
            policy=self._policy,
        )


def results_only(ranked: list[RankedResult]) -> list[KnowledgeSearchResult]:
    """Convenience: the plain `list[KnowledgeSearchResult]` ready for
    `app.engine.knowledge.context.ContextBuilder.build(...)`, unchanged
    from Stage 6A's own consumption contract."""
    return [item.result for item in ranked]


__all__ = ["AdaptiveRetriever", "RankedResult", "results_only"]
