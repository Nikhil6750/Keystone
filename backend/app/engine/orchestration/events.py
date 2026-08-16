"""Stage 8C.2: provider-neutral orchestration execution events.

Mirrors the existing `app.engine.workflow.events.StateSink` pattern (the
scheduler's own event-emission port) rather than inventing a new shape:
one small `Protocol` (`OrchestrationEventSink`), one frozen event type
(`OrchestrationEvent`), and a simple local monotonic counter
(`OrchestrationEventSequence`, matching `scheduler.py`'s own
`_SequenceCounter`).

**No FastAPI/SSE/HTTP import here or anywhere else in this package** (see
`app/engine/orchestration/__init__.py`'s own module docstring) -- the API
layer (`app/api/routes/orchestrations.py`) adapts these events to
Server-Sent Events; this module knows nothing about that.

**Safety, structurally enforced.** Every field on `OrchestrationEvent` is a
bounded, typed, already-safe fact (an id, a status enum value, a short
message) -- there is deliberately no `payload: dict[str, Any]` escape hatch
here (contrast `WorkflowExecutionEvent.payload`), so nothing upstream can
accidentally smuggle a raw provider response, `reasoning_content`, a
prompt, or a stack trace into an event by putting it in an untyped blob.
`message` is documented as short, human-readable, and observable-only.

**Sequencing differs from `StateSink` on purpose.** `GraphScheduler` owns
one `_SequenceCounter` for the lifetime of one `run()` call and is the only
emitter. Here, TWO independent emitters exist for one execution: the API
coordinator (which emits `execution.accepted` before any orchestration work
starts) and `EndToEndOrchestrationService.orchestrate()` (which emits every
event after that). Both must draw from the *same* counter for `sequence` to
be genuinely monotonic across one execution, so `OrchestrationEventSequence`
is public and passed explicitly from the coordinator into the service
(`EndToEndOrchestrationService(..., event_sequence=...)`) rather than being
a private implementation detail of one component.

**Failure isolation differs from `StateSink` on purpose, too.**
`StateSink.on_event` failures are documented as fail-fast by design there.
Stage 8C.2's event sink is deliberately the opposite: a broken/slow event
sink must never turn a verified orchestration success into a business
failure (see `service.py`'s emission wrapper) -- instrumentation is
observational, never load-bearing for correctness.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class OrchestrationEventType(StrEnum):
    """The Stage 8C.2 event taxonomy. Deliberately coarse -- one event per
    meaningful state transition, never per internal function call."""

    EXECUTION_ACCEPTED = "execution.accepted"
    EXECUTION_STARTED = "execution.started"

    KNOWLEDGE_STARTED = "knowledge.started"
    KNOWLEDGE_COMPLETED = "knowledge.completed"

    MANAGER_STARTED = "manager.started"
    MANAGER_COMPLETED = "manager.completed"
    MANAGER_FALLBACK = "manager.fallback"

    GOAL_RECEIVED = "goal.received"
    PLANNING_STARTED = "planning.started"
    PLANNING_COMPLETED = "planning.completed"

    TEAM_ASSEMBLED = "team.assembled"

    TASK_READY = "task.ready"
    TASK_WAITING = "task.waiting"
    AGENT_SELECTED = "agent.selected"

    ROUTING_STARTED = "routing.started"
    ROUTING_TASK_SELECTED = "routing.task_selected"
    ROUTING_FAILED = "routing.failed"

    WORKFLOW_CREATED = "workflow.created"
    WORKFLOW_STARTED = "workflow.started"

    STEP_STARTED = "step.started"
    STEP_COMPLETED = "step.completed"
    STEP_FAILED = "step.failed"

    WORKSPACE_CREATED = "workspace.created"
    INTEGRATION_STARTED = "integration.started"
    INTEGRATION_CONFLICT = "integration.conflict"
    INTEGRATION_COMPLETED = "integration.completed"

    FILE_ACTIVITY = "file.activity"
    EXECUTION_HEARTBEAT = "execution.heartbeat"
    EXECUTION_PROGRESS = "execution.progress"

    VERIFICATION_STARTED = "verification.started"
    VERIFICATION_COMPLETED = "verification.completed"

    RECOVERY_STARTED = "recovery.started"
    RECOVERY_COMPLETED = "recovery.completed"
    RECOVERY_EXHAUSTED = "recovery.exhausted"

    LEARNING_COMPLETED = "learning.completed"

    RETRIEVAL_FEEDBACK_COMPLETED = "retrieval_feedback.completed"

    EXECUTION_COMPLETED = "execution.completed"
    EXECUTION_FAILED = "execution.failed"
    EXECUTION_CANCELLED = "execution.cancelled"


@dataclass(frozen=True)
class OrchestrationEvent:
    """One observable fact about one execution's progress. Every field is
    bounded and safe by construction -- see module docstring. `safe_issue_codes`
    reuses the same stable, machine-readable code vocabulary
    `OrchestrationResult.issue_codes` already uses; never a raw message."""

    event_id: str
    execution_id: str
    sequence: int
    event_type: OrchestrationEventType
    timestamp: datetime
    phase: str | None = None
    status: str | None = None
    workflow_id: str | None = None
    task_key: str | None = None
    agent_id: str | None = None
    attempt_number: int | None = None
    verification_status: str | None = None
    safe_issue_codes: tuple[str, ...] = field(default_factory=tuple)
    message: str | None = None
    elapsed_seconds: float | None = None
    relative_path: str | None = None
    activity: str | None = None
    previous_agent_id: str | None = None
    new_agent_id: str | None = None
    reason_category: str | None = None


class OrchestrationEventSink(Protocol):
    """Receives one `OrchestrationEvent` per meaningful state transition.
    A caller with no interest in events uses `NullEventSink` (the default
    everywhere one is accepted) -- nothing here requires a sink to exist."""

    async def on_event(self, event: OrchestrationEvent) -> None: ...


class NullEventSink:
    """The default `OrchestrationEventSink`: discards every event. Ensures
    every existing Stage 8C.1 caller (none of which pass `event_sink=`)
    observes zero behavior change -- constructing this and calling
    `on_event` is always a legal no-op, never `None`-checked by callers."""

    async def on_event(self, event: OrchestrationEvent) -> None:
        return None


class OrchestrationEventSequence:
    """A simple monotonic counter, shared by every emitter for one
    execution (mirrors `app.engine.workflow.scheduler._SequenceCounter`,
    made public here since two independent components share one instance
    -- see module docstring)."""

    def __init__(self) -> None:
        self._value = 0

    def next(self) -> int:
        self._value += 1
        return self._value


__all__ = [
    "NullEventSink",
    "OrchestrationEvent",
    "OrchestrationEventSequence",
    "OrchestrationEventSink",
    "OrchestrationEventType",
]
