"""The Metric Aggregator: deterministic, pure-function reduction of a list
of `LearningEvent`s into `AgentPassportMetricBucket`/`VerificationMetrics`
values for one bucket (overall, one task type, one repository, one
capability, or -- Stage 5B's finest-grained dimension -- one
`(repository, task type)` pair).

**Deterministic by construction**: every function here is a symmetric
aggregate (count, sum, max, sorted-percentile) over its input event list --
none of them depend on input order, none call `datetime.now()`, none use
randomness, none call an external model. See `passport.py` for the
higher-level per-agent orchestration built on top of these functions.

**Execution success != verified success**, tracked as two entirely
separate tallies here (see `events.py`): `_bucket_from_events` counts
`execution_status`; `_verification_metrics_from_events` counts
`verification_status` -- summing or comparing the two is never done
anywhere in this module.
"""

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from app.contracts.enums import AgentExecutionStatus
from app.contracts.passports import AgentPassportMetricBucket
from app.contracts.verification import VerificationStatus
from app.engine.learning.events import LearningEvent

# Matches `app.engine.routing.scorer._MIN_SAMPLE_SIZE_FOR_CONFIDENCE`'s
# threshold (5) so Stage 5A's `low_sample_size` flag means the same thing
# Stage 4B's scorer already means by it. Kept as an independent constant
# rather than importing that module-private name across packages.
MIN_SAMPLE_SIZE_FOR_CONFIDENCE = 5


@dataclass(frozen=True)
class VerificationMetrics:
    """Verification-derived tallies for one bucket, kept structurally
    separate from `AgentPassportMetricBucket`'s execution counts (which
    have no verification fields at all) -- execution success and verified
    success must never be confused or added together.

    `verified_success_rate` is `None`, never `0.0`, when
    `verification_sample_count` is `0`: "no verification evidence exists"
    is a different fact from "verification always failed," and collapsing
    them would fabricate a measured rate from zero samples.
    """

    verified_success_count: int = 0
    verification_failure_count: int = 0
    verification_inconclusive_count: int = 0
    human_review_count: int = 0
    verification_sample_count: int = 0
    verified_success_rate: float | None = None


@dataclass(frozen=True)
class LearningBucket:
    """One dimension's full evidence: the Router-facing execution/latency
    metrics (`AgentPassportMetricBucket`) plus the Stage 5A-only
    verification tallies (`VerificationMetrics`)."""

    metrics: AgentPassportMetricBucket
    verification: VerificationMetrics


def percentile(sorted_ascending_values: list[float], target_percentile: float) -> float:
    """Nearest-rank percentile over an already-ascending-sorted list.

    `rank = ceil(target_percentile / 100 * n)`, clamped to `[1, n]`, then
    the `(rank - 1)`-indexed (0-based) value is returned directly -- no
    interpolation between adjacent values. This is a single, deterministic
    formula shared by every percentile Stage 5A computes (p50 and p95
    alike); it deliberately does not average the two middle values for an
    even-sized input (a different, equally valid median convention) --
    documented here precisely so callers/tests know exactly which value to
    expect rather than guessing at an ambiguous "the median."

    `sorted_ascending_values` must be non-empty and already sorted
    ascending; callers (this module's own `_bucket_from_events`) guarantee
    both before calling.
    """
    n = len(sorted_ascending_values)
    rank = math.ceil((target_percentile / 100.0) * n)
    rank = max(1, min(n, rank))
    return sorted_ascending_values[rank - 1]


def _verification_metrics_from_events(events: list[LearningEvent]) -> VerificationMetrics:
    verified_success = 0
    verification_failure = 0
    verification_inconclusive = 0
    human_review = 0
    for event in events:
        status = event.verification_status
        if status is VerificationStatus.PASSED:
            verified_success += 1
        elif status is VerificationStatus.FAILED:
            verification_failure += 1
        elif status is VerificationStatus.INCONCLUSIVE:
            verification_inconclusive += 1
        elif status is VerificationStatus.REQUIRES_HUMAN_REVIEW:
            human_review += 1
        # status is None: verification never occurred for this event --
        # contributes to no verification tally at all.

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


def bucket_from_events(events: list[LearningEvent]) -> LearningBucket:
    """The full `LearningBucket` (execution metrics + verification tallies)
    for one dimension's event list.

    Execution counting rule: `execution_count` includes every event in
    `events` (successes, failures, timeouts, and cancellations alike --
    all of them were genuinely attempted executions). `success_count`
    counts only `SUCCEEDED`. `failure_count` counts `FAILED` and
    `TIMED_OUT` (a timeout is an objectively failed outcome).
    `CANCELLED` events are deliberately counted in neither
    `success_count` nor `failure_count` -- per Stage 5A's explicit rule,
    a cancellation is not an ordinary success or failure -- while still
    counting toward `execution_count`, so `execution_count` can
    legitimately exceed `success_count + failure_count` whenever
    cancellations exist.

    Latency: `median_latency_ms` is computed from every event with a
    real (non-`None`) `duration_ms`, regardless of outcome -- a failed or
    cancelled execution's measured duration is still real evidence of how
    long that agent's executions take.
    """
    execution_count = len(events)
    success_count = sum(
        1 for event in events if event.execution_status is AgentExecutionStatus.SUCCEEDED
    )
    failure_count = sum(
        1
        for event in events
        if event.execution_status
        in (AgentExecutionStatus.FAILED, AgentExecutionStatus.TIMED_OUT)
    )

    durations = sorted(event.duration_ms for event in events if event.duration_ms is not None)
    median_latency_ms = percentile(durations, 50) if durations else None

    sample_size = execution_count
    low_sample_size = sample_size < MIN_SAMPLE_SIZE_FOR_CONFIDENCE

    metrics = AgentPassportMetricBucket(
        execution_count=execution_count,
        success_count=success_count,
        failure_count=failure_count,
        median_latency_ms=median_latency_ms,
        low_sample_size=low_sample_size,
    )
    verification = _verification_metrics_from_events(events)
    return LearningBucket(metrics=metrics, verification=verification)


def group_and_bucket(
    events: list[LearningEvent], key: Callable[[LearningEvent], str | None]
) -> dict[str, LearningBucket]:
    """Group `events` by `key(event)` (skipping events where `key` returns
    `None` -- they simply don't contribute to this bucket dimension) and
    build a `LearningBucket` per group. Iterates `events` in the given
    order to build each group's list, but the resulting buckets are
    themselves order-independent aggregates (see `bucket_from_events`)."""
    groups: dict[str, list[LearningEvent]] = {}
    for event in events:
        group_key = key(event)
        if group_key is None:
            continue
        groups.setdefault(group_key, []).append(event)
    return {
        group_key: bucket_from_events(group_events) for group_key, group_events in groups.items()
    }


def group_by_capability_and_bucket(events: list[LearningEvent]) -> dict[str, LearningBucket]:
    """Like `group_and_bucket`, but one event can belong to multiple
    capability groups at once (`LearningEvent.capabilities` is a tuple) --
    an event with two declared capabilities contributes to both capability
    buckets independently."""
    groups: dict[str, list[LearningEvent]] = {}
    for event in events:
        for capability in event.capabilities:
            groups.setdefault(capability.value, []).append(event)
    return {
        group_key: bucket_from_events(group_events) for group_key, group_events in groups.items()
    }


def group_by_repository_task_type_and_bucket(
    events: list[LearningEvent],
) -> dict[tuple[str, str], LearningBucket]:
    """Group `events` by the `(repository_id, task_type)` pair -- Stage 5B's
    finest-grained evidence dimension (`app.engine.learning.policy`'s
    hierarchy priority 1). Only real, observed joint evidence: an event
    contributes here only when it carries *both* a `repository_id` and a
    `task_type`; this is additional real aggregation over the same raw
    events the other three dimensions already use, never a fabricated
    blend of the separate repository/task-type buckets."""
    groups: dict[tuple[str, str], list[LearningEvent]] = {}
    for event in events:
        if event.repository_id is None or event.task_type is None:
            continue
        key = (event.repository_id, event.task_type)
        groups.setdefault(key, []).append(event)
    return {
        group_key: bucket_from_events(group_events) for group_key, group_events in groups.items()
    }


def count_failure_categories(events: Iterable[LearningEvent]) -> dict[str, int]:
    """Deterministic failure-category tally (keyed by `FailureCategory.value`)
    across every event with a real `failure_category`. Dict key insertion
    order tracks first-occurrence order in `events`, but equality (and
    therefore semantic Passport comparison) never depends on that order."""
    counts: dict[str, int] = {}
    for event in events:
        if event.failure_category is not None:
            key = event.failure_category.value
            counts[key] = counts.get(key, 0) + 1
    return counts


__all__ = [
    "MIN_SAMPLE_SIZE_FOR_CONFIDENCE",
    "LearningBucket",
    "VerificationMetrics",
    "bucket_from_events",
    "count_failure_categories",
    "group_and_bucket",
    "group_by_capability_and_bucket",
    "group_by_repository_task_type_and_bucket",
    "percentile",
]
