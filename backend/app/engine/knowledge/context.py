"""`ContextBuilder`: turns ranked `KnowledgeSearchResult`s into a bounded,
deduplicated, provenance-preserving `ContextResult` for downstream
Planner/Orchestrator/agent consumption.

**Not a prompt builder.** This module returns structured context only --
chunk content plus provenance -- never a formatted prompt string for
Claude, Nemotron, or any other model. Prompt assembly is explicitly out of
scope for Stage 6A (see the module-level task description); a future
stage's prompt builder would consume `ContextResult` as its input.

**Never partially truncates a chunk.** A chunk is included whole or not at
all -- there is no code path that slices `chunk.content` to make it fit
the remaining budget. Cutting a chunk's content would corrupt its
`content_hash`/provenance identity (the hash would no longer describe what
was actually included); skipping it entirely preserves that identity, so
"destroys provenance identity" (the Stage 6A requirement this directly
satisfies) can never happen.

**Deterministic, budget-respecting, dedup-aware.** `results` are processed
in rank order (defensively re-sorted by `(rank, chunk_id)` even if the
caller passes them out of order); a chunk already selected by `chunk_id`
or by `content_hash` (two different chunks with byte-identical content,
e.g. from two sources describing the same fact) is skipped, never
duplicated in the output.
"""

from dataclasses import dataclass, field

from app.engine.knowledge.errors import MalformedKnowledgeDataError
from app.engine.knowledge.models import KnowledgeProvenance
from app.engine.knowledge.retrieval import KnowledgeSearchResult


@dataclass(frozen=True)
class ContextBudget:
    """Explicit, documented context-selection limits."""

    max_chunks: int = 10
    max_total_chars: int = 4000

    def __post_init__(self) -> None:
        if self.max_chunks <= 0:
            raise MalformedKnowledgeDataError("max_chunks must be positive")
        if self.max_total_chars <= 0:
            raise MalformedKnowledgeDataError("max_total_chars must be positive")


@dataclass(frozen=True)
class ContextChunk:
    """One chunk selected into the final context, with its provenance."""

    content: str
    provenance: KnowledgeProvenance


@dataclass(frozen=True)
class ContextResult:
    """The deterministic output of `ContextBuilder.build`."""

    chunks: tuple[ContextChunk, ...] = field(default_factory=tuple)
    total_chars: int = 0
    truncated: bool = False


class ContextBuilder:
    """Stateless: `build` is a pure function of its arguments."""

    def build(
        self, results: list[KnowledgeSearchResult], budget: ContextBudget | None = None
    ) -> ContextResult:
        budget = budget or ContextBudget()
        ordered = sorted(results, key=lambda result: (result.rank, result.chunk.chunk_id))

        selected: list[ContextChunk] = []
        seen_chunk_ids: set[str] = set()
        seen_content_hashes: set[str] = set()
        total_chars = 0

        for result in ordered:
            if len(selected) >= budget.max_chunks:
                break
            chunk = result.chunk
            if chunk.chunk_id in seen_chunk_ids:
                continue
            if chunk.content_hash in seen_content_hashes:
                continue
            chunk_chars = len(chunk.content)
            if total_chars + chunk_chars > budget.max_total_chars:
                # Never partially include a chunk to make it fit -- skip
                # it and keep looking for a smaller one that does, rather
                # than stopping selection entirely at the first oversized
                # candidate.
                continue
            selected.append(ContextChunk(content=chunk.content, provenance=result.provenance))
            seen_chunk_ids.add(chunk.chunk_id)
            seen_content_hashes.add(chunk.content_hash)
            total_chars += chunk_chars

        truncated = len(selected) < len(ordered)
        return ContextResult(chunks=tuple(selected), total_chars=total_chars, truncated=truncated)


__all__ = ["ContextBudget", "ContextBuilder", "ContextChunk", "ContextResult"]
