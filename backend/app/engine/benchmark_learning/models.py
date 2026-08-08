"""Stage 7B domain models: the explicit `PRODUCTION`/`BENCHMARK` evidence-
source concept, and the local provenance record that carries the benchmark
facts a shared `LearningEvent` (`app.engine.learning.events`) structurally
cannot -- `suite_id`, `case_id`, and `repetition`.

**Why a local record instead of a contract change.** `LearningEvent` is a
closed, no-open-field type by design (see its own module docstring): every
field is a scalar or a member of an existing typed enum, deliberately with
no `dict[str, Any]` anywhere. Adding `suite_id`/`case_id`/`repetition`
fields to it would be a shared-contract change affecting every production
caller of Stage 5, for a concept (benchmarking) Stage 5 itself has no
reason to know about. Instead, Stage 7B keeps `LearningEvent` untouched and
carries the extra provenance in `BenchmarkLearningProvenance`, joined back
to its `LearningEvent` by `event_id`. This directly answers "did this
learning evidence come from production execution or benchmark execution?"
-- a `LearningEvent` with no matching `BenchmarkLearningProvenance` is
production evidence; one with a provenance record is benchmark evidence,
explicitly and only via that record's presence, never via a guessed field
on `LearningEvent` itself.

**No open field here either.** Every field on `BenchmarkLearningProvenance`
is a scalar identifier or a member of an existing typed enum -- the same
"no place for unsafe content to hide" guarantee `LearningEvent` already
has, inherited by construction rather than re-implemented.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.contracts.enums import AgentExecutionStatus
from app.contracts.verification import VerificationStatus
from app.engine.benchmark_learning.errors import MalformedBenchmarkLearningInputError
from app.engine.learning.events import LearningEvent


class EvidenceSource(StrEnum):
    """Where a `LearningEvent` actually came from. Never inferred, never
    defaulted silently -- every `BenchmarkLearningProvenance` carries
    `BENCHMARK` explicitly; `PRODUCTION` exists so callers building a
    combined view (e.g. a future advisory report) have a matching, equally
    explicit label to use for their own production-sourced events, without
    Stage 7B ever guessing at it."""

    PRODUCTION = "production"
    BENCHMARK = "benchmark"


@dataclass(frozen=True)
class BenchmarkLearningProvenance:
    """The benchmark-specific facts one `LearningEvent` cannot carry itself.

    `campaign_id` identifies *which run* of the suite this observation
    belongs to -- it is what distinguishes two genuinely separate
    executions of the same `suite_id`/`case_id`/`agent_type`/`repetition`
    (e.g. re-running the same suite a week later): without it, those two
    executions would be indistinguishable and idempotent conversion would
    incorrectly collapse them into one event identity.

    Always `source=EvidenceSource.BENCHMARK` -- there is no other way to
    construct this type, so its mere presence (joined to a `LearningEvent`
    by `event_id`) is itself the "this came from a benchmark, not
    production" signal.
    """

    event_id: str
    campaign_id: str
    suite_id: str
    case_id: str
    agent_type: str
    repetition: int
    execution_status: AgentExecutionStatus
    verification_status: VerificationStatus
    source: EvidenceSource = EvidenceSource.BENCHMARK

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise MalformedBenchmarkLearningInputError("event_id must not be blank")
        if not self.campaign_id.strip():
            raise MalformedBenchmarkLearningInputError("campaign_id must not be blank")
        if not self.suite_id.strip():
            raise MalformedBenchmarkLearningInputError("suite_id must not be blank")
        if not self.case_id.strip():
            raise MalformedBenchmarkLearningInputError("case_id must not be blank")
        if not self.agent_type.strip():
            raise MalformedBenchmarkLearningInputError("agent_type must not be blank")
        if self.repetition < 1:
            raise MalformedBenchmarkLearningInputError("repetition must be at least 1")
        if self.source is not EvidenceSource.BENCHMARK:
            raise MalformedBenchmarkLearningInputError(
                "BenchmarkLearningProvenance.source must always be EvidenceSource.BENCHMARK"
            )


@dataclass(frozen=True)
class BenchmarkLearningRecord:
    """One converted benchmark observation: the shared-shape `LearningEvent`
    ready for existing Stage 5 aggregation, paired with the benchmark
    provenance that would otherwise be lost. Always keep `event` and
    `provenance` together -- an `event` alone (once mixed into a larger
    event list) is indistinguishable from a production event, which is
    exactly why this record exists."""

    event: LearningEvent
    provenance: BenchmarkLearningProvenance

    def __post_init__(self) -> None:
        if self.event.event_id != self.provenance.event_id:
            raise MalformedBenchmarkLearningInputError(
                "BenchmarkLearningRecord.event.event_id must match "
                "BenchmarkLearningRecord.provenance.event_id"
            )
        if self.event.agent_type != self.provenance.agent_type:
            raise MalformedBenchmarkLearningInputError(
                "BenchmarkLearningRecord.event.agent_type must match "
                "BenchmarkLearningRecord.provenance.agent_type"
            )
        if self.event.verification_status != self.provenance.verification_status:
            raise MalformedBenchmarkLearningInputError(
                "BenchmarkLearningRecord.event.verification_status must match "
                "BenchmarkLearningRecord.provenance.verification_status"
            )
        if self.event.execution_status != self.provenance.execution_status:
            raise MalformedBenchmarkLearningInputError(
                "BenchmarkLearningRecord.event.execution_status must match "
                "BenchmarkLearningRecord.provenance.execution_status"
            )


__all__ = [
    "BenchmarkLearningProvenance",
    "BenchmarkLearningRecord",
    "EvidenceSource",
]
