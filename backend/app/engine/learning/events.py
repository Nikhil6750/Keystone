"""`LearningEvent`: a provider-neutral, observable record of one completed
execution/outcome -- the raw material Stage 5A's aggregator turns into an
`AgentPassport`.

**Raw events are the source of truth** (see `passport.py`'s module
docstring): a `LearningEvent` is never itself a computed/aggregate value,
only a direct transcription of what was actually observed for one
execution attempt.

**Execution success != verified success**, deliberately never collapsed
into one boolean: `execution_status` (did the agent process return
successfully?) and `verification_status` (did Stage 4E confirm the *output*
satisfied its `ExpectedOutcome`?) are two independent, optional-in-relation-
to-each-other fields. An execution can succeed while its output fails
verification (`execution_status=SUCCEEDED`, `verification_status=FAILED`);
an execution can fail before verification ever runs at all
(`execution_status=FAILED`, `verification_status=None`).

**No open-ended metadata field, by design.** Every field here is a scalar,
a `str | None`, or a member of an existing typed enum
(`AgentExecutionStatus`, `FailureCategory`, `VerificationStatus`,
`RuntimeKind`, `AgentCapability`) -- there is deliberately no
`dict[str, Any]`/`value: Any` field anywhere on this type. That is Stage
5A's actual safety guarantee against reasoning-shaped content, raw prompts,
or credentials ever entering a `LearningEvent`: there is no place for such
content to hide, not merely a runtime check bolted onto an open field.

**No absolute filesystem paths.** `repository_id` is validated at
construction to reject anything that looks like an absolute path (a
leading `/` or `\\`, a Windows drive prefix like `C:\\`, or a `..`
traversal segment) -- consistent with `RepositoryMetadata`'s own documented
intent (`app.contracts.adapter`) that a repository identifier is opaque,
provider-neutral metadata, never a local filesystem path.
"""

import math
import re
from dataclasses import dataclass
from datetime import datetime

from app.contracts.enums import AgentCapability, AgentExecutionStatus, RuntimeKind
from app.contracts.errors import FailureCategory
from app.contracts.verification import VerificationStatus
from app.engine.learning.errors import MalformedLearningEventError

_ABSOLUTE_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _looks_like_unsafe_repository_id(value: str) -> bool:
    """True if `value` looks like an absolute filesystem path or contains a
    `..` traversal segment, rather than an opaque repository identifier
    (e.g. `"org/repo"`, a UUID, a slug)."""
    if value.startswith("/") or value.startswith("\\"):
        return True
    if _ABSOLUTE_DRIVE_PATH_RE.match(value):
        return True
    segments = re.split(r"[\\/]", value)
    return ".." in segments


@dataclass(frozen=True)
class LearningEvent:
    """One completed execution attempt's observable outcome.

    `attempt_number` alone carries "retry information" (`attempt_number > 1`
    means this was a retry) and `execution_status is CANCELLED` alone
    carries "cancellation" -- neither gets a redundant boolean field, since
    a second field expressing the same fact as a first could drift out of
    sync with it; a raw event should have exactly one way to say each
    thing.
    """

    event_id: str
    workflow_id: str
    agent_type: str
    execution_status: AgentExecutionStatus
    created_at: datetime

    attempt_number: int = 1
    step_id: str | None = None
    runtime_kind: RuntimeKind | None = None
    task_type: str | None = None
    repository_id: str | None = None
    capabilities: tuple[AgentCapability, ...] = ()
    failure_category: FailureCategory | None = None
    duration_ms: float | None = None
    verification_status: VerificationStatus | None = None
    cost_usd: float | None = None

    def __post_init__(self) -> None:
        self._validate_identifiers()
        self._validate_numeric_fields()
        self._validate_repository_id()
        self._validate_status_failure_category_pairing()

    def _validate_identifiers(self) -> None:
        if not self.event_id.strip():
            raise MalformedLearningEventError("event_id must not be blank")
        if not self.workflow_id.strip():
            raise MalformedLearningEventError("workflow_id must not be blank")
        if not self.agent_type.strip():
            raise MalformedLearningEventError("agent_type must not be blank")
        if self.step_id is not None and not self.step_id.strip():
            raise MalformedLearningEventError("step_id must not be blank if provided")
        if self.task_type is not None and not self.task_type.strip():
            raise MalformedLearningEventError("task_type must not be blank if provided")
        if self.attempt_number < 1:
            raise MalformedLearningEventError("attempt_number must be at least 1")

    def _validate_numeric_fields(self) -> None:
        if self.duration_ms is not None and (
            not math.isfinite(self.duration_ms) or self.duration_ms < 0
        ):
            raise MalformedLearningEventError("duration_ms must be finite and non-negative")
        if self.cost_usd is not None and (not math.isfinite(self.cost_usd) or self.cost_usd < 0):
            raise MalformedLearningEventError("cost_usd must be finite and non-negative")

    def _validate_repository_id(self) -> None:
        if self.repository_id is None:
            return
        if not self.repository_id.strip():
            raise MalformedLearningEventError("repository_id must not be blank if provided")
        if _looks_like_unsafe_repository_id(self.repository_id):
            raise MalformedLearningEventError(
                f"repository_id must not look like an absolute filesystem path: "
                f"{self.repository_id!r}"
            )

    def _validate_status_failure_category_pairing(self) -> None:
        """Mirrors `AgentExecutionResult`'s own invariant
        (`app.contracts.adapter`) locally, so a `LearningEvent` built
        directly (not projected from an `AgentExecutionResult`) is just as
        internally consistent."""
        status = self.execution_status
        category = self.failure_category
        if status is AgentExecutionStatus.SUCCEEDED and category is not None:
            raise MalformedLearningEventError(
                "failure_category must be None when execution_status is SUCCEEDED"
            )
        if status is AgentExecutionStatus.FAILED and category is None:
            raise MalformedLearningEventError(
                "failure_category is required when execution_status is FAILED"
            )
        if status is AgentExecutionStatus.CANCELLED and category is not FailureCategory.CANCELLED:
            raise MalformedLearningEventError(
                "failure_category must be CANCELLED when execution_status is CANCELLED"
            )
        if status is AgentExecutionStatus.TIMED_OUT and category is not FailureCategory.TIMEOUT:
            raise MalformedLearningEventError(
                "failure_category must be TIMEOUT when execution_status is TIMED_OUT"
            )


__all__ = ["LearningEvent"]
