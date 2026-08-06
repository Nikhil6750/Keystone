"""The scheduler's event-emission port.

`StateSink` is the "restart-safe persisted state preparation" seam: the
scheduler calls it for every state transition, so a future persistence layer
can subscribe without this package knowing about SQLAlchemy or any storage
engine. No implementation here writes to a database — see
`tests/support/graph_fakes.py::RecordingStateSink` for the in-memory
implementation exercised by tests.
"""

from typing import Protocol

from app.contracts.workflow import WorkflowExecutionEvent


class StateSink(Protocol):
    """Receives one `WorkflowExecutionEvent` per scheduler state transition."""

    async def on_event(self, event: WorkflowExecutionEvent) -> None: ...


__all__ = ["StateSink"]
