"""Stage 7.5 domain model: `RetrievalObservation`, the typed, immutable
record of one retrieval decision -- what Stage 6A's base retrieval
returned, and what was actually selected into the agent's context.

**Query safety.** No raw query text is ever stored on this type -- only
`query_fingerprint`, a deterministic `sha256` hex digest of the
normalized (stripped, lowercased, whitespace-collapsed) query string (see
`compute_query_fingerprint`). Two observations for the same effective
query always fingerprint identically; the original text is never
recoverable from the fingerprint and is never persisted here.

**Base retrieval stays authoritative, structurally.** `__post_init__`
rejects any `selected_chunk_ids` entry that is not also present in
`retrieved_chunk_ids` -- Stage 7.5 cannot even *construct* an observation
claiming a chunk was selected that Stage 6A's own base retrieval did not
return as a candidate in the first place. This is a hard, load-bearing
invariant, not just a design intention documented in `reranking.py`.

**Deterministic retrieval-set identity.** `retrieval_id` is computed
automatically (never caller-supplied, never a random UUID) from
`query_fingerprint`/`task_type`/`repository_id`/the *ordered*
`selected_chunk_ids` -- the stable facts that define "this is the same
semantic retrieval" per the Stage 7.5 spec. `created_at` is excluded from
identity and from dataclass comparison (`compare=False`): it is an
operational fact about *when this was observed*, never data any
computation depends on.
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime

from app.engine.adaptive_retrieval.errors import MalformedRetrievalObservationError

_ABSOLUTE_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _looks_like_unsafe_path(value: str) -> bool:
    """True if `value` looks like an absolute filesystem path or contains a
    `..` traversal segment, rather than an opaque identifier -- the same
    check `app.engine.learning.events`/`app.engine.benchmark.models`
    independently apply to their own `repository_id` fields."""
    if value.startswith("/") or value.startswith("\\"):
        return True
    if _ABSOLUTE_DRIVE_PATH_RE.match(value):
        return True
    segments = re.split(r"[\\/]", value)
    return ".." in segments


def compute_query_fingerprint(query: str) -> str:
    """A deterministic, non-reversible `sha256` fingerprint of `query`'s
    normalized form (stripped, lowercased, internal whitespace collapsed to
    a single space) -- never the raw query text itself. Two queries that
    differ only in case/whitespace fingerprint identically; the fingerprint
    reveals nothing about the original text beyond exact-normalized-match."""
    normalized = " ".join(query.strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _retrieval_id(
    query_fingerprint: str,
    task_type: str | None,
    repository_id: str | None,
    selected_chunk_ids: tuple[str, ...],
) -> str:
    """Pure function of stable, semantic retrieval facts only -- never a
    timestamp, never random. Order of `selected_chunk_ids` is part of the
    identity (a differently-ordered context selection is a different
    semantic retrieval)."""
    task_part = task_type or ""
    repository_part = repository_id or ""
    selected_part = ",".join(selected_chunk_ids)
    return f"retrieval::{query_fingerprint}::{task_part}::{repository_part}::{selected_part}"


@dataclass(frozen=True)
class RetrievalObservation:
    """One retrieval decision: what Stage 6A's base retrieval returned
    (`retrieved_chunk_ids`/`original_ranks`/`original_scores`, in Stage
    6A's own order) and what was actually selected into the agent's
    context (`selected_chunk_ids`), for one query against one
    task/repository context.
    """

    query_fingerprint: str
    task_type: str | None = None
    repository_id: str | None = None
    agent_type: str | None = None
    retrieved_chunk_ids: tuple[str, ...] = ()
    retrieved_chunk_content_hashes: tuple[str, ...] = ()
    original_ranks: tuple[int, ...] = ()
    original_scores: tuple[float, ...] = ()
    selected_chunk_ids: tuple[str, ...] = ()
    campaign_id: str | None = None
    created_at: datetime | None = field(default=None, compare=False)

    retrieval_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.query_fingerprint.strip():
            raise MalformedRetrievalObservationError("query_fingerprint must not be blank")
        if self.task_type is not None and not self.task_type.strip():
            raise MalformedRetrievalObservationError("task_type must not be blank if provided")
        if self.repository_id is not None:
            if not self.repository_id.strip():
                raise MalformedRetrievalObservationError(
                    "repository_id must not be blank if provided"
                )
            if _looks_like_unsafe_path(self.repository_id):
                raise MalformedRetrievalObservationError(
                    f"repository_id must not look like an absolute filesystem path: "
                    f"{self.repository_id!r}"
                )
        if self.agent_type is not None and not self.agent_type.strip():
            raise MalformedRetrievalObservationError("agent_type must not be blank if provided")

        parallel_lengths = {
            len(self.retrieved_chunk_ids),
            len(self.retrieved_chunk_content_hashes),
            len(self.original_ranks),
            len(self.original_scores),
        }
        if len(parallel_lengths) != 1:
            raise MalformedRetrievalObservationError(
                "retrieved_chunk_ids/retrieved_chunk_content_hashes/original_ranks/"
                "original_scores must all be the same length"
            )
        if len(set(self.retrieved_chunk_ids)) != len(self.retrieved_chunk_ids):
            raise MalformedRetrievalObservationError(
                "retrieved_chunk_ids must not contain duplicates"
            )

        retrieved_set = set(self.retrieved_chunk_ids)
        unretrieved_selections = [
            chunk_id for chunk_id in self.selected_chunk_ids if chunk_id not in retrieved_set
        ]
        if unretrieved_selections:
            raise MalformedRetrievalObservationError(
                "selected_chunk_ids must be a subset of retrieved_chunk_ids -- Stage 7.5 "
                f"cannot select a chunk Stage 6A's base retrieval did not return: "
                f"{unretrieved_selections!r}"
            )
        if len(set(self.selected_chunk_ids)) != len(self.selected_chunk_ids):
            raise MalformedRetrievalObservationError(
                "selected_chunk_ids must not contain duplicates"
            )

        if self.campaign_id is not None and not self.campaign_id.strip():
            raise MalformedRetrievalObservationError("campaign_id must not be blank if provided")

        object.__setattr__(
            self,
            "retrieval_id",
            _retrieval_id(
                self.query_fingerprint,
                self.task_type,
                self.repository_id,
                self.selected_chunk_ids,
            ),
        )

    def content_hash_for(self, chunk_id: str) -> str | None:
        """The recorded content hash for `chunk_id` at observation time, or
        `None` if `chunk_id` was not part of `retrieved_chunk_ids`."""
        try:
            index = self.retrieved_chunk_ids.index(chunk_id)
        except ValueError:
            return None
        return self.retrieved_chunk_content_hashes[index]


__all__ = ["RetrievalObservation", "compute_query_fingerprint"]
