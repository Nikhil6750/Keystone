"""`BenchmarkLearningAdapter`: converts Stage 7A `BenchmarkExecutionResult`s
into Stage 5 `LearningEvent`s, and builds benchmark-only `LearningPassport`s
from them through the *existing*, unmodified Stage 5 aggregation pipeline.

    BenchmarkExecutionResult
            |
            v
    convert_benchmark_result_to_learning_event / ..._results_to_learning_records
            |
            v
    BenchmarkLearningRecord (LearningEvent + BenchmarkLearningProvenance)
            |
            v
    BenchmarkLearningPolicy.filter_records  (explicit opt-in gate)
            |
            v
    build_benchmark_learning_passports  ->  app.engine.learning.passport.rebuild_all_passports
            |
            v
    LearningPassport  (benchmark-only; never merged into a production
                        PassportEvidenceProvider by anything in this module)

**No duplicated aggregation.** Every count, rate, and percentile in the
resulting `LearningPassport` is computed by Stage 5A's own
`rebuild_passport`/`rebuild_all_passports` (`app.engine.learning.passport`)
-- this module performs zero arithmetic of its own beyond field mapping and
identity derivation. "Raw events are the source of truth" (Stage 5A's own
invariant) applies unchanged to benchmark-derived events.

**No weighting.** Stage 7B is evidence integration, not adaptive scoring:
a benchmark-derived `LearningEvent` is aggregated by exactly the same
formulas as a production one, with no numeric discount or boost applied
anywhere in this module. If a future stage wants benchmark-informed priors,
that is an explicit, separately-reviewed policy decision -- not something
this adapter does implicitly by, say, converting fewer benchmark events
than were supplied, or scaling a rate.

**Production isolation is structural, not enforced by a runtime check.**
This module never imports `app.engine.routing` or constructs a
`PassportEvidenceProvider`/`Router`. A caller who wants benchmark evidence
to inform a production routing decision must explicitly build a *separate*
`PassportEvidenceProvider` from a benchmark-only event list and pass it to
`Router(evidence=...)` themselves -- nothing here does that automatically,
and nothing here mutates a `PassportEvidenceProvider` or `LearningPassport`
a caller already built from production events.

**Mapping decisions worth calling out explicitly:**

- `event_id`/`workflow_id` are pure functions of `suite_id`/`case_id`/
  `agent_type`/`repetition` -- never a random UUID, never derived from
  `created_at` or from the observed outcome. The same benchmark execution
  slot always yields the same identity, regardless of what its outcome
  was, so a caller can idempotently reconvert without producing duplicate
  semantic events. (`repetition` is baked into `event_id`, not
  `workflow_id`, so every repetition of the same case still shares one
  `workflow_id` -- consistent with treating a benchmark case as one
  logical "workflow" run repeated `N` times.)
- `attempt_number` is always `1`, deliberately never set to
  `repetition`. `LearningEvent.attempt_number` means "this was a retry of
  the same attempt" and directly feeds `LearningPassport`/`AgentPassport`
  `retry_count` (`attempt_number > 1`) and, downstream, Stage 5B's
  `RETRY_HISTORY` reason code and score penalty. A benchmark repetition is
  an independent statistical trial, not a retry -- mapping it onto
  `attempt_number` would silently inflate a benchmark-derived passport's
  retry rate in proportion to `repeat_count`, corrupting a real Stage 5B
  scoring signal. `repetition` is preserved losslessly instead in
  `BenchmarkLearningProvenance.repetition`.
- `step_id` is mapped from `case_id` -- a benchmark case genuinely is
  "which step of this workflow" in the same sense `step_id` already means
  for a production `LearningEvent`, so this is direct reuse, not
  overloading an unrelated field.
- `created_at` is never fabricated with `datetime.now()`. Callers may pass
  an explicit `created_at` (applied uniformly to the whole call), and
  otherwise each result's own `BenchmarkExecutionResult.created_at` is
  used; if neither is available, conversion raises rather than inventing a
  timestamp, matching Stage 5A/7A's own "no current time" discipline.
- `duration_ms`, `cost_usd`, `failure_category`, `verification_status`,
  `task_type`, `repository_id` are all direct, lossless passthroughs --
  `BenchmarkExecutionResult` and `LearningEvent` already agree on these
  types field-for-field, so there is nothing to estimate, fabricate, or
  reinterpret.
"""

from collections.abc import Iterable
from datetime import datetime

from app.engine.benchmark.models import BenchmarkExecutionResult
from app.engine.benchmark_learning.errors import (
    BenchmarkLearningIdentityConflictError,
    MalformedBenchmarkLearningInputError,
)
from app.engine.benchmark_learning.models import (
    BenchmarkLearningProvenance,
    BenchmarkLearningRecord,
)
from app.engine.learning.events import LearningEvent
from app.engine.learning.passport import LearningPassport, rebuild_all_passports


def _event_id(suite_id: str, case_id: str, agent_type: str, repetition: int) -> str:
    """Pure function of stable benchmark facts only -- never the outcome,
    never a timestamp, never random. Same inputs always yield the same
    identity, so re-converting the same benchmark execution slot (even
    with a different, later-updated outcome) always maps to the same
    `event_id`."""
    return f"benchmark::{suite_id}::{case_id}::{agent_type}::rep{repetition}"


def _workflow_id(suite_id: str) -> str:
    return f"benchmark::{suite_id}"


def convert_benchmark_result_to_learning_event(
    result: BenchmarkExecutionResult, *, created_at: datetime | None = None
) -> BenchmarkLearningRecord:
    """Convert one `BenchmarkExecutionResult` into a `BenchmarkLearningRecord`
    (a `LearningEvent` plus its `BenchmarkLearningProvenance`).

    `created_at`, if supplied, is used as-is; otherwise `result.created_at`
    is used. If neither is available, raises
    `MalformedBenchmarkLearningInputError` -- this module never calls
    `datetime.now()` to paper over a missing timestamp.
    """
    resolved_created_at = created_at if created_at is not None else result.created_at
    if resolved_created_at is None:
        raise MalformedBenchmarkLearningInputError(
            "cannot convert a BenchmarkExecutionResult with no created_at: pass one "
            "explicitly or ensure the result itself carries one"
        )

    event_id = _event_id(result.suite_id, result.case_id, result.agent_type, result.repetition)
    workflow_id = _workflow_id(result.suite_id)

    event = LearningEvent(
        event_id=event_id,
        workflow_id=workflow_id,
        agent_type=result.agent_type,
        execution_status=result.execution_status,
        created_at=resolved_created_at,
        attempt_number=1,
        step_id=result.case_id,
        runtime_kind=None,
        task_type=result.task_type,
        repository_id=result.repository_id,
        capabilities=(),
        failure_category=result.failure_category,
        duration_ms=result.duration_ms,
        verification_status=result.verification_status,
        cost_usd=result.cost_usd,
    )

    provenance = BenchmarkLearningProvenance(
        event_id=event_id,
        suite_id=result.suite_id,
        case_id=result.case_id,
        agent_type=result.agent_type,
        repetition=result.repetition,
        execution_status=result.execution_status,
        verification_status=result.verification_status,
    )

    return BenchmarkLearningRecord(event=event, provenance=provenance)


def convert_benchmark_results_to_learning_records(
    results: Iterable[BenchmarkExecutionResult], *, created_at: datetime | None = None
) -> list[BenchmarkLearningRecord]:
    """Convert many `BenchmarkExecutionResult`s into a deterministic,
    duplicate-free list of `BenchmarkLearningRecord`s.

    - Ordering is always by `event_id` ascending, regardless of input
      order -- the same set of results in any shuffled order produces the
      same output list.
    - A byte-identical duplicate (same `event_id`, same resulting
      `LearningEvent`) is kept once, silently.
    - Two results that share an `event_id`
      (`suite_id`/`case_id`/`agent_type`/`repetition`) but convert to a
      *different* `LearningEvent` -- a genuine data conflict, e.g. the same
      benchmark slot reported with two different outcomes in one batch --
      raises `BenchmarkLearningIdentityConflictError` rather than silently
      picking one.
    """
    by_id: dict[str, BenchmarkLearningRecord] = {}
    for result in results:
        record = convert_benchmark_result_to_learning_event(result, created_at=created_at)
        existing = by_id.get(record.event.event_id)
        if existing is not None and existing.event != record.event:
            raise BenchmarkLearningIdentityConflictError(
                f"benchmark result identity '{record.event.event_id}' was converted twice "
                "with different observable content in the same batch"
            )
        by_id[record.event.event_id] = record

    return [by_id[event_id] for event_id in sorted(by_id)]


def build_benchmark_learning_passports(
    records: Iterable[BenchmarkLearningRecord], *, updated_at: datetime
) -> dict[str, LearningPassport]:
    """Build benchmark-only `LearningPassport`s (one per `agent_type`) from
    already-filtered `BenchmarkLearningRecord`s, via the existing,
    unmodified Stage 5 `rebuild_all_passports` -- no aggregation formula is
    reimplemented here.

    The result is a benchmark-only view: it reflects only whatever
    `records` were supplied (typically the output of
    `BenchmarkLearningPolicy.filter_records`), never any production
    evidence, and is never automatically combined with, or written into,
    a production `PassportEvidenceProvider`/`Router`.
    """
    events = [record.event for record in records]
    return rebuild_all_passports(events, updated_at=updated_at)


__all__ = [
    "build_benchmark_learning_passports",
    "convert_benchmark_result_to_learning_event",
    "convert_benchmark_results_to_learning_records",
]
