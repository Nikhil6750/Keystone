"""Stage 7.5 `RetrievalPassport`: deterministic, fully recomputable
per-chunk retrieval evidence built from raw `RetrievalFeedback` -- mirrors
Stage 5A's "raw events are the source of truth" invariant
(`app.engine.learning.passport`) exactly, one dimension over.

**Reuses `VerificationMetrics` directly.** The verified-success tally
shape Stage 7.5 needs per chunk (`verified_success_count`/
`verification_failure_count`/`verification_inconclusive_count`/
`human_review_count`/`verification_sample_count`/`verified_success_rate`,
with `None` -- never `0.0` -- for a zero-sample rate) is *exactly*
`app.engine.learning.aggregation.VerificationMetrics`, so this module
imports and reuses that type unchanged rather than declaring a duplicate
one. What this module computes locally is only the *counting* over
`RetrievalFeedback` (a different object shape than `LearningEvent`, so
Stage 5A's own private `_verification_metrics_from_events` cannot be
called directly) -- the underlying formula (only `PASSED` is success, a
zero-sample rate is `None`) is identical by construction, not
independently re-derived.

**Deterministic, order-independent.** Every function here is a symmetric
aggregate (count, sum) over its input feedback list -- none depend on
input order, none call `datetime.now()`, none use randomness. Rebuilding
from the same feedback set (in any order) always yields an identical
semantic `RetrievalPassport`.

**Evidence hierarchy**, most to least specific -- mirrors Stage 5B's own
tier order (`app.engine.learning.policy._select_tier`):

    1. repository + task type
    2. task type
    3. repository
    4. overall

`scoring.py` is what actually walks this hierarchy against a minimum
sample-size gate; this module only computes each tier's bucket.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

from app.contracts.verification import VerificationStatus
from app.engine.adaptive_retrieval.feedback import RetrievalFeedback
from app.engine.learning.aggregation import VerificationMetrics


@dataclass(frozen=True)
class RetrievalBucket:
    """One dimension's evidence for one chunk: how often it was retrieved
    versus actually selected, plus the verified-outcome tally for the
    feedback that referenced it."""

    retrieval_count: int
    selected_count: int
    verification: VerificationMetrics


@dataclass(frozen=True)
class RetrievalPassport:
    """One chunk's full, recomputable retrieval evidence."""

    chunk_id: str
    overall: RetrievalBucket
    task_type_buckets: dict[str, RetrievalBucket] = field(default_factory=dict)
    repository_buckets: dict[str, RetrievalBucket] = field(default_factory=dict)
    repository_task_type_buckets: dict[tuple[str, str], RetrievalBucket] = field(
        default_factory=dict
    )
    agent_buckets: dict[str, RetrievalBucket] = field(default_factory=dict)


def _verification_metrics(feedback: list[RetrievalFeedback]) -> VerificationMetrics:
    """Counts each feedback record's `verification_status` exactly once,
    toward exactly one tally -- the same rule Stage 5A's own (private,
    `LearningEvent`-shaped) counter applies, reimplemented here only
    because the input object shape differs. Only `PASSED` ever
    contributes to `verified_success_count`."""
    verified_success = 0
    verification_failure = 0
    verification_inconclusive = 0
    human_review = 0
    for item in feedback:
        status = item.verification_status
        if status is VerificationStatus.PASSED:
            verified_success += 1
        elif status is VerificationStatus.FAILED:
            verification_failure += 1
        elif status is VerificationStatus.INCONCLUSIVE:
            verification_inconclusive += 1
        elif status is VerificationStatus.REQUIRES_HUMAN_REVIEW:
            human_review += 1

    sample_count = (
        verified_success + verification_failure + verification_inconclusive + human_review
    )
    verified_success_rate = (verified_success / sample_count) if sample_count > 0 else None

    return VerificationMetrics(
        verified_success_count=verified_success,
        verification_failure_count=verification_failure,
        verification_inconclusive_count=verification_inconclusive,
        human_review_count=human_review,
        verification_sample_count=sample_count,
        verified_success_rate=verified_success_rate,
    )


def _bucket(feedback: list[RetrievalFeedback], *, chunk_id: str) -> RetrievalBucket:
    """`retrieval_count`/`selected_count` are currently equal: `feedback`
    is filtered to records whose `chunk_ids` already contains `chunk_id`
    (a *selected* reference), and Stage 7.5 does not yet separately track
    "retrieved but not selected" observations feeding a passport (only
    `RetrievalObservation` itself, not `RetrievalFeedback`, sees the full
    retrieved candidate set). Both fields are kept distinct on the type so
    a future stage can populate `retrieval_count` from
    `RetrievalObservation` history without a shape change here."""
    count = len(feedback)
    return RetrievalBucket(
        retrieval_count=count, selected_count=count, verification=_verification_metrics(feedback)
    )


def rebuild_retrieval_passport(
    feedback: Iterable[RetrievalFeedback],
    *,
    chunk_id: str,
    current_content_hash: str | None = None,
) -> RetrievalPassport:
    """Deterministically rebuild `chunk_id`'s `RetrievalPassport` from
    `feedback`. Feedback not referencing `chunk_id` is ignored.

    **Stale-evidence guard.** When `current_content_hash` is supplied
    (typically looked up live from the current `KnowledgeIndex`), any
    feedback record whose `content_hash_for(chunk_id)` disagrees with it
    is excluded -- old evidence recorded against since-changed chunk
    content must never silently transfer to today's content. When
    `current_content_hash` is `None` (no live index available, e.g. a pure
    rebuild-from-raw-feedback test), no staleness filtering happens.
    """
    relevant = [item for item in feedback if chunk_id in item.chunk_ids]
    if current_content_hash is not None:
        relevant = [
            item
            for item in relevant
            if item.content_hash_for(chunk_id) in (None, current_content_hash)
        ]

    overall = _bucket(relevant, chunk_id=chunk_id)

    by_task: dict[str, list[RetrievalFeedback]] = {}
    by_repository: dict[str, list[RetrievalFeedback]] = {}
    by_repository_task: dict[tuple[str, str], list[RetrievalFeedback]] = {}
    by_agent: dict[str, list[RetrievalFeedback]] = {}
    for item in relevant:
        if item.task_type is not None:
            by_task.setdefault(item.task_type, []).append(item)
        if item.repository_id is not None:
            by_repository.setdefault(item.repository_id, []).append(item)
        if item.repository_id is not None and item.task_type is not None:
            by_repository_task.setdefault((item.repository_id, item.task_type), []).append(item)
        if item.agent_type is not None:
            by_agent.setdefault(item.agent_type, []).append(item)

    return RetrievalPassport(
        chunk_id=chunk_id,
        overall=overall,
        task_type_buckets={
            key: _bucket(items, chunk_id=chunk_id) for key, items in by_task.items()
        },
        repository_buckets={
            key: _bucket(items, chunk_id=chunk_id) for key, items in by_repository.items()
        },
        repository_task_type_buckets={
            key: _bucket(items, chunk_id=chunk_id) for key, items in by_repository_task.items()
        },
        agent_buckets={key: _bucket(items, chunk_id=chunk_id) for key, items in by_agent.items()},
    )


def rebuild_all_retrieval_passports(
    feedback: Iterable[RetrievalFeedback],
    *,
    current_content_hashes: dict[str, str] | None = None,
) -> dict[str, RetrievalPassport]:
    """Group `feedback` by every chunk id it references and rebuild each
    chunk's `RetrievalPassport` in one pass. `current_content_hashes`, if
    given, maps `chunk_id -> current content hash` for the stale-evidence
    guard (see `rebuild_retrieval_passport`); a chunk id absent from the
    mapping gets no staleness filtering."""
    chunk_ids: set[str] = set()
    for item in feedback:
        chunk_ids.update(item.chunk_ids)

    feedback_list = list(feedback)
    hashes = current_content_hashes or {}
    return {
        chunk_id: rebuild_retrieval_passport(
            feedback_list, chunk_id=chunk_id, current_content_hash=hashes.get(chunk_id)
        )
        for chunk_id in sorted(chunk_ids)
    }


__all__ = [
    "RetrievalBucket",
    "RetrievalPassport",
    "rebuild_all_retrieval_passports",
    "rebuild_retrieval_passport",
]
