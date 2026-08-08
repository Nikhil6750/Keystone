"""The scheduler's event-emission port.

`StateSink` is the "restart-safe persisted state preparation" seam: the
scheduler calls it for every state transition, so a future persistence layer
can subscribe without this package knowing about SQLAlchemy or any storage
engine. No implementation here writes to a database — see
`tests/support/graph_fakes.py::RecordingStateSink` for the in-memory
implementation exercised by tests.

**Current behavior, by design (not yet redesigned for persistence):**

- `GraphScheduler` always `await`s `sink.on_event(event)` inline, in the same
  single coroutine that drives scheduling, never fire-and-forget and never
  backgrounded. This is what keeps event/sequence-number ordering
  deterministic — moving emission off the critical path would reintroduce the
  same kind of ordering ambiguity this stage just removed from the skip
  cascade.
- A `on_event()` failure is **fail-fast**, deliberately: it propagates
  straight out of `run()` uncaught. Losing an execution-state/audit event
  silently is not an acceptable failure mode, so a broken sink aborting the
  run (rather than continuing on cheerfully with gaps in the record) is the
  intended behavior for now, not an oversight.
- A slow sink correspondingly slows scheduling — since emission is inline,
  `sink.on_event()` latency adds directly to the time before the next batch
  of ready steps is launched. Acceptable at today's scale; revisit if a real
  persistence-backed sink's latency becomes a throughput concern.
- `sequence_number` is monotonic only *within one `run()` call*, starting
  back at 1 every time. It is not yet safe to persist under a
  `(workflow_id, sequence_number)` uniqueness constraint the way the existing
  `AuditEvent` table does, because a second `run()` for the same
  `workflow_id` (e.g. a future scheduler-level resume) would collide with the
  first run's numbers. Durable persistence, replay, and sequence-number
  continuity across resume are explicitly deferred to future
  integration/persistence work, not addressed here.
"""

from typing import Protocol

from app.contracts.workflow import WorkflowExecutionEvent


class StateSink(Protocol):
    """Receives one `WorkflowExecutionEvent` per scheduler state transition."""

    async def on_event(self, event: WorkflowExecutionEvent) -> None: ...


__all__ = ["StateSink"]
