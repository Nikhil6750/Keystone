"""Stage 7.5 `RetrievalFeedback`: the immutable, verified feedback record
that turns one `RetrievalObservation` into learnable evidence -- plus the
storage-neutral `RetrievalFeedbackRepository` Protocol Abhinav's
persistence layer will implement separately.

**Only objective verification produces positive evidence.** `PASSED` is
the only `VerificationStatus` counted as verified retrieval success
anywhere downstream (`passport.py`); `FAILED` is negative evidence;
`INCONCLUSIVE`/`REQUIRES_HUMAN_REVIEW` are recorded as samples but never
promoted to success. `execution_status` is carried purely as observable
context -- an execution that `SUCCEEDED` with `verification_status=FAILED`
must never be (and, since only `verification_status` feeds
`is_verified_success`, structurally cannot be) counted as retrieval
success. See `models.py`'s module docstring for why no raw query text
exists on this type either.

**Benchmark vs production, never blended.** `evidence_source` reuses
Stage 7B's own `EvidenceSource` (`app.engine.benchmark_learning.models`)
rather than inventing a duplicate concept. `campaign_id` mirrors Stage
7B's `BenchmarkLearningProvenance` invariant exactly: required and
non-blank when `evidence_source` is `BENCHMARK`, forbidden when
`PRODUCTION`. Separation is enforced at the aggregation boundary in
`passport.py`, never inside this type: a caller builds one
`RetrievalPassport` from production-only feedback and a separate one from
benchmark-only feedback, and never concatenates the two lists together.

**Shared, non-causal attribution.** `chunk_ids` is the *entire* selected
context set from the source `RetrievalObservation` -- every chunk in it
receives the exact same verification signal from this one feedback record
(no per-chunk weighting by rank/position). This is deliberately weak
evidence: "this chunk co-occurred in a retrieval with this verified
outcome," never "this chunk caused this outcome." `retrieval_id` retains
the link back to the full retrieval set, so a future ablation/
counterfactual study can still group feedback by retrieval and compare
overlapping vs. disjoint chunk sets -- nothing here destroys that
information.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from app.contracts.enums import AgentExecutionStatus
from app.contracts.verification import VerificationStatus
from app.engine.adaptive_retrieval.errors import (
    MalformedRetrievalFeedbackError,
    RetrievalFeedbackConflictError,
)
from app.engine.benchmark_learning.models import EvidenceSource


def _feedback_id(
    retrieval_id: str,
    verification_status: VerificationStatus,
    execution_status: AgentExecutionStatus | None,
    evidence_source: EvidenceSource,
    campaign_id: str | None,
) -> str:
    """Pure function of the observable verified outcome -- never a
    timestamp, never random. Re-recording the identical verified outcome
    for the same retrieval always yields the same `feedback_id`."""
    execution_part = execution_status.value if execution_status is not None else ""
    campaign_part = campaign_id or ""
    return (
        "feedback::"
        f"{retrieval_id}::{verification_status.value}::{execution_part}::"
        f"{evidence_source.value}::{campaign_part}"
    )


@dataclass(frozen=True)
class RetrievalFeedback:
    """One verified outcome attributed (weakly, non-causally) to the chunks
    selected by one `RetrievalObservation`."""

    retrieval_id: str
    chunk_ids: tuple[str, ...]
    verification_status: VerificationStatus
    task_type: str | None = None
    repository_id: str | None = None
    agent_type: str | None = None
    execution_status: AgentExecutionStatus | None = None
    evidence_source: EvidenceSource = EvidenceSource.PRODUCTION
    campaign_id: str | None = None
    chunk_content_hashes: tuple[str, ...] = ()
    created_at: datetime | None = field(default=None, compare=False)

    feedback_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.retrieval_id.strip():
            raise MalformedRetrievalFeedbackError("retrieval_id must not be blank")
        if not self.chunk_ids:
            raise MalformedRetrievalFeedbackError("chunk_ids must not be empty")
        if len(set(self.chunk_ids)) != len(self.chunk_ids):
            raise MalformedRetrievalFeedbackError("chunk_ids must not contain duplicates")
        if self.chunk_content_hashes and len(self.chunk_content_hashes) != len(self.chunk_ids):
            raise MalformedRetrievalFeedbackError(
                "chunk_content_hashes, if provided, must be the same length as chunk_ids"
            )
        if self.task_type is not None and not self.task_type.strip():
            raise MalformedRetrievalFeedbackError("task_type must not be blank if provided")
        if self.repository_id is not None and not self.repository_id.strip():
            raise MalformedRetrievalFeedbackError("repository_id must not be blank if provided")
        if self.agent_type is not None and not self.agent_type.strip():
            raise MalformedRetrievalFeedbackError("agent_type must not be blank if provided")

        if self.evidence_source is EvidenceSource.BENCHMARK:
            if self.campaign_id is None or not self.campaign_id.strip():
                raise MalformedRetrievalFeedbackError(
                    "campaign_id is required and must not be blank when "
                    "evidence_source is EvidenceSource.BENCHMARK"
                )
        elif self.campaign_id is not None:
            raise MalformedRetrievalFeedbackError(
                "campaign_id must be None when evidence_source is EvidenceSource.PRODUCTION"
            )

        object.__setattr__(
            self,
            "feedback_id",
            _feedback_id(
                self.retrieval_id, self.verification_status, self.execution_status,
                self.evidence_source, self.campaign_id,
            ),
        )

    @property
    def is_verified_success(self) -> bool:
        """The only positive-evidence condition anywhere in Stage 7.5:
        `verification_status is VerificationStatus.PASSED`. Never
        `execution_status`, never any other field."""
        return self.verification_status is VerificationStatus.PASSED

    @property
    def is_verified_failure(self) -> bool:
        return self.verification_status is VerificationStatus.FAILED

    def content_hash_for(self, chunk_id: str) -> str | None:
        if not self.chunk_content_hashes:
            return None
        try:
            index = self.chunk_ids.index(chunk_id)
        except ValueError:
            return None
        return self.chunk_content_hashes[index]


class RetrievalFeedbackRepository(Protocol):
    """Storage-neutral seam for persisting `RetrievalFeedback`. A future
    PostgreSQL/Supabase-backed implementation satisfies this Protocol
    without Stage 7.5 knowing or caring -- no SQLAlchemy model, migration,
    network call, or credential exists anywhere in this package."""

    def add(self, feedback: RetrievalFeedback) -> None:
        """Idempotent for a byte-identical re-add (same `feedback_id`, same
        content); raises `RetrievalFeedbackConflictError` for a genuine
        conflict (same `feedback_id`, different content)."""
        ...

    def all(self) -> list[RetrievalFeedback]:
        """Every stored feedback record, in a stable, deterministic order."""
        ...


class InMemoryRetrievalFeedbackRepository:
    """In-memory `RetrievalFeedbackRepository` for Stage 7.5 tests and
    local use. Not a substitute for real persistence -- exists purely so
    Stage 7.5 can be exercised end to end without a database."""

    def __init__(self, feedback: Iterable[RetrievalFeedback] = ()) -> None:
        self._by_id: dict[str, RetrievalFeedback] = {}
        for item in feedback:
            self.add(item)

    def add(self, feedback: RetrievalFeedback) -> None:
        existing = self._by_id.get(feedback.feedback_id)
        if existing is not None and existing != feedback:
            raise RetrievalFeedbackConflictError(
                f"feedback identity '{feedback.feedback_id}' was recorded twice "
                "with different observable content"
            )
        self._by_id[feedback.feedback_id] = feedback

    def all(self) -> list[RetrievalFeedback]:
        return [self._by_id[key] for key in sorted(self._by_id)]


__all__ = [
    "InMemoryRetrievalFeedbackRepository",
    "RetrievalFeedback",
    "RetrievalFeedbackRepository",
]
