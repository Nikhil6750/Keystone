"""Agent Passport: derived, fully recomputable state built from raw
`LearningEvent`s.

**Raw events are the source of truth, load-bearing invariant**: an
`AgentPassport` (and this module's richer `LearningPassport` wrapper) is
never itself persisted-as-authoritative or hand-edited -- it is always the
output of `rebuild_passport(events, ...)` applied to the full ordered (or
unordered; see below) set of `LearningEvent`s for one `agent_type`. Given
the same set of events, `rebuild_passport` always returns a semantically
identical `LearningPassport`, regardless of the order those events were
supplied in -- every quantity computed here (counts, sums, max-of-
timestamps, sorted-percentiles) is a symmetric aggregate over the event
set, never a running/incremental computation sensitive to sequence.

**No current time.** `updated_at` is always a caller-supplied
`datetime` (an operational fact about *when this rebuild happened*, not
data used in any metric calculation) -- this module never calls
`datetime.now()` itself, so `rebuild_passport` is a pure function of its
arguments and safely repeatable in tests without time-freezing.
`last_succeeded_at`/`last_verified_at` are computed differently: they are
the maximum `LearningEvent.created_at` among the relevant events -- real
historical data carried on the events themselves, not live time.

**`AgentPassport` (`app.contracts.passports`) is reused completely
unmodified** as the Router-facing projection: `LearningPassport.passport`
*is* a real `AgentPassport`, directly usable as
`PassportEvidenceProvider` evidence (see `evidence.py`). `AgentPassport`
has no capability-bucket field and no verified-success fields today, so
`LearningPassport` carries those as additional, engine-layer-only
attributes alongside the untouched contract object -- never by changing
the contract itself.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from app.contracts.enums import AgentExecutionStatus
from app.contracts.passports import AgentPassport, AgentPassportMetricBucket
from app.engine.learning.aggregation import (
    LearningBucket,
    VerificationMetrics,
    bucket_from_events,
    count_failure_categories,
    group_and_bucket,
    group_by_capability_and_bucket,
    group_by_repository_task_type_and_bucket,
    percentile,
)
from app.engine.learning.events import LearningEvent


@dataclass(frozen=True)
class LearningPassport:
    """Stage 5A's full recomputable view for one `agent_type`.

    `passport` is the exact, unmodified `AgentPassport` contract, built by
    *projecting* `task_type_buckets`/`repository_buckets` (its
    `task_type_metrics`/`repository_metrics` are literally the `.metrics`
    of those same buckets) -- never computed independently, so the two
    representations can never drift apart. `overall_metrics` mirrors
    `passport`'s own top-level counts in `AgentPassportMetricBucket` shape,
    for direct use as `RoutingEvidenceProvider.overall_metrics` evidence.

    `capability_buckets`, `repository_task_type_buckets`, and every
    bucket's `.verification` (plus `overall_verification`) exist only
    here: `AgentPassport` has no capability dimension, no joint
    repository+task-type dimension, and no verified-success fields yet.
    `repository_task_type_buckets` (added for Stage 5B's evidence
    hierarchy) is real aggregation over the same raw events as every other
    dimension -- grouped by `(repository_id, task_type)` -- never a
    fabricated blend of the separate `repository_buckets`/
    `task_type_buckets`.
    """

    passport: AgentPassport
    overall_metrics: AgentPassportMetricBucket
    overall_verification: VerificationMetrics
    task_type_buckets: dict[str, LearningBucket] = field(default_factory=dict)
    repository_buckets: dict[str, LearningBucket] = field(default_factory=dict)
    capability_buckets: dict[str, LearningBucket] = field(default_factory=dict)
    repository_task_type_buckets: dict[tuple[str, str], LearningBucket] = field(
        default_factory=dict
    )
    known_cost_usd_average: float | None = None
    known_cost_sample_count: int = 0


def _max_created_at(timestamps: Iterable[datetime]) -> datetime | None:
    result: datetime | None = None
    for timestamp in timestamps:
        if result is None or timestamp > result:
            result = timestamp
    return result


def _known_cost_average(events: list[LearningEvent]) -> tuple[float | None, int]:
    """Real cost evidence only: the average of every event's actually-known
    `cost_usd`, or `(None, 0)` when no event reports one. Never fabricated,
    never defaulted to `0.0`."""
    known = [event.cost_usd for event in events if event.cost_usd is not None]
    if not known:
        return None, 0
    return sum(known) / len(known), len(known)


def rebuild_passport(
    events: Iterable[LearningEvent], *, agent_type: str, updated_at: datetime
) -> LearningPassport:
    """Deterministically rebuild `agent_type`'s `LearningPassport` from
    `events`. Events for other agent types are ignored (not an error --
    callers commonly hold one combined event stream across many agents).

    Same `events` (in any order) for the same `agent_type` always produce
    an identical semantic `LearningPassport` -- `updated_at` is the only
    field that varies independently of the event set, by design (see
    module docstring).
    """
    relevant = [event for event in events if event.agent_type == agent_type]

    overall_bucket = bucket_from_events(relevant)
    durations = sorted(event.duration_ms for event in relevant if event.duration_ms is not None)
    p95_latency_ms = percentile(durations, 95) if durations else None

    cancellation_count = sum(
        1 for event in relevant if event.execution_status is AgentExecutionStatus.CANCELLED
    )
    retry_count = sum(1 for event in relevant if event.attempt_number > 1)

    failure_categories = count_failure_categories(relevant)

    last_succeeded_at = _max_created_at(
        event.created_at
        for event in relevant
        if event.execution_status is AgentExecutionStatus.SUCCEEDED
    )
    last_verified_at = _max_created_at(
        event.created_at for event in relevant if event.verification_status is not None
    )

    task_type_buckets = group_and_bucket(relevant, key=lambda event: event.task_type)
    repository_buckets = group_and_bucket(relevant, key=lambda event: event.repository_id)
    capability_buckets = group_by_capability_and_bucket(relevant)
    repository_task_type_buckets = group_by_repository_task_type_and_bucket(relevant)

    known_cost_usd_average, known_cost_sample_count = _known_cost_average(relevant)

    passport = AgentPassport(
        agent_type=agent_type,
        execution_count=overall_bucket.metrics.execution_count,
        success_count=overall_bucket.metrics.success_count,
        failure_count=overall_bucket.metrics.failure_count,
        cancellation_count=cancellation_count,
        retry_count=retry_count,
        median_latency_ms=overall_bucket.metrics.median_latency_ms,
        p95_latency_ms=p95_latency_ms,
        failure_categories=failure_categories,
        task_type_metrics={key: bucket.metrics for key, bucket in task_type_buckets.items()},
        repository_metrics={key: bucket.metrics for key, bucket in repository_buckets.items()},
        low_sample_size=overall_bucket.metrics.low_sample_size,
        last_verified_at=last_verified_at,
        last_succeeded_at=last_succeeded_at,
        updated_at=updated_at,
    )

    return LearningPassport(
        passport=passport,
        overall_metrics=overall_bucket.metrics,
        overall_verification=overall_bucket.verification,
        task_type_buckets=task_type_buckets,
        repository_buckets=repository_buckets,
        capability_buckets=capability_buckets,
        repository_task_type_buckets=repository_task_type_buckets,
        known_cost_usd_average=known_cost_usd_average,
        known_cost_sample_count=known_cost_sample_count,
    )


def rebuild_all_passports(
    events: Iterable[LearningEvent], *, updated_at: datetime
) -> dict[str, LearningPassport]:
    """Group `events` by `agent_type` and rebuild every agent's
    `LearningPassport` in one pass. Equivalent to calling `rebuild_passport`
    once per distinct `agent_type` present in `events`."""
    by_agent: dict[str, list[LearningEvent]] = {}
    for event in events:
        by_agent.setdefault(event.agent_type, []).append(event)
    return {
        agent_type: rebuild_passport(agent_events, agent_type=agent_type, updated_at=updated_at)
        for agent_type, agent_events in by_agent.items()
    }


__all__ = ["LearningPassport", "rebuild_all_passports", "rebuild_passport"]
