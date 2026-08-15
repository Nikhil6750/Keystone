"""Stage 8C.2: the bounded application-level execution job layer (Part 3).

`OrchestrationExecutionCoordinator` starts one orchestration per `start()`
call as an isolated background `asyncio.Task`, with its own freshly-built
`EndToEndOrchestrationService` instance (and therefore its own DB session --
see `service_factory`'s docstring on why that matters), so concurrent
executions never share mutable state. `start()` itself never awaits the
orchestration -- it returns as soon as the execution record exists and the
background task has been scheduled, which is what lets the API layer return
`202 Accepted` quickly instead of holding the HTTP request open for the
whole pipeline (see `app/api/routes/orchestrations.py`).

`OrchestrationExecutionStore` is the storage-neutral seam (Part 3
requirement 1-3): `InMemoryOrchestrationExecutionStore` is the only
implementation this stage ships, and it is explicitly **not** restart-safe
-- every execution record and every event lives in this process's memory
only, and is lost on restart (see its own docstring). A future
persistence-backed implementation satisfies the same Protocol; nothing else
in this package (or the API layer) would need to change to swap it in.

**No FastAPI/SSE/HTTP import anywhere in this module** -- see
`app/engine/orchestration/__init__.py`'s own module docstring. The API
layer adapts `OrchestrationExecutionStore.subscribe()`/`get_events()` to
Server-Sent Events; this module knows nothing about that.

**Job status vs. business outcome, deliberately distinct (Part 19).**
`OrchestrationExecutionStatus` (accepted/running/completed/failed/cancelled)
describes the *transport/job* lifecycle only. `OrchestrationResult.outcome`
(`VERIFIED_SUCCESS`/`NO_ELIGIBLE_ROUTE`/`RECOVERY_EXHAUSTED`/...) is a
completely separate, already-certified Stage 8C.1 concept: an execution
whose `orchestrate()` call *returns normally* is job `status=completed`
regardless of which business outcome it reached -- `orchestrate()` only
raises for a genuinely unexpected failure (a `ManagerError` that somehow
escaped `ManagerOrchestrator`'s own fallback handling, or a persistence
error), which is the only case mapped to job `status=failed` here.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from app.engine.manager.errors import ManagerError
from app.engine.orchestration.errors import OrchestrationPersistenceError
from app.engine.orchestration.events import (
    OrchestrationEvent,
    OrchestrationEventSequence,
    OrchestrationEventSink,
    OrchestrationEventType,
)
from app.engine.orchestration.models import OrchestrationRequest, OrchestrationResult
from app.engine.orchestration.service import EndToEndOrchestrationService
from app.resilience.circuit_breaker import CircuitBreakerOpenError

logger = logging.getLogger(__name__)

_DEFAULT_MAX_EVENT_HISTORY = 2000
_DEFAULT_SUBSCRIBER_QUEUE_SIZE = 200

# Recognized, Keystone-owned exception types whose own `str(exc)` is already
# a safe, documented, non-provider-derived message (mirrors the exact same
# allowlist-by-type discipline `app/api/errors.py` already applies to HTTP
# responses) -- anything else falls back to a fully generic message, never
# `str(exc)`, since an unrecognized exception could in principle carry
# provider/runtime content.
_SAFE_SUMMARY_EXCEPTION_TYPES: tuple[type[Exception], ...] = (
    OrchestrationPersistenceError,
    ManagerError,
    # `WorkflowEngine.execute_workflow()`'s own documented contract: it
    # raises this when a step's circuit was already open before its first
    # attempt (recovery-cycle re-opens are already caught closer to the
    # source in `service.py::_run_recovery_cycle`, producing a normal
    # `RecoveryAction.FAIL` outcome instead of reaching here at all -- this
    # entry is the outer safety net for the same exception type escaping
    # any other call site). `str(exc)` is just an agent_type name, safe to
    # surface.
    CircuitBreakerOpenError,
)


def _safe_error_summary(exc: Exception) -> str:
    """A bounded, safe-to-store-and-display summary of an execution
    failure -- never the raw exception string for an unrecognized type."""
    if isinstance(exc, _SAFE_SUMMARY_EXCEPTION_TYPES):
        return f"{type(exc).__name__}: {exc}"
    return f"{type(exc).__name__}: an unexpected internal error occurred"


class OrchestrationExecutionStatus(StrEnum):
    """Transport/job lifecycle only -- never conflated with
    `OrchestrationOutcome` (see module docstring)."""

    ACCEPTED = "accepted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class OrchestrationExecutionRecord:
    """One execution's current, observable job state."""

    execution_id: str
    status: OrchestrationExecutionStatus
    result: OrchestrationResult | None = None
    error_summary: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class OrchestrationExecutionStore(Protocol):
    """Storage-neutral seam for execution job records and their event
    history. Also structurally satisfies `OrchestrationEventSink`
    (`on_event`) -- the store *is* the sink for this stage; a future
    implementation could still separate the two if it ever needed to."""

    async def create(self, execution_id: str) -> None: ...

    async def get(self, execution_id: str) -> OrchestrationExecutionRecord | None: ...

    async def update_status(
        self, execution_id: str, status: OrchestrationExecutionStatus
    ) -> None: ...

    async def set_result(self, execution_id: str, result: OrchestrationResult) -> None: ...

    async def set_error(self, execution_id: str, error_summary: str) -> None: ...

    async def on_event(self, event: OrchestrationEvent) -> None: ...

    async def get_events(
        self, execution_id: str, *, after_sequence: int = 0
    ) -> list[OrchestrationEvent]: ...

    def subscribe(
        self, execution_id: str
    ) -> "AbstractAsyncContextManager[asyncio.Queue[OrchestrationEvent | None]]": ...


class InMemoryOrchestrationExecutionStore:
    """Process-local, in-memory `OrchestrationExecutionStore` +
    `OrchestrationEventSink`.

    **Not restart-safe.** Every execution record and every event lives
    entirely in this object's memory and is lost on process restart --
    there is no database write anywhere in this class. Acceptable for
    Stage 8C.2 (Part 3 requirement 3); a future persistence-backed
    implementation of `OrchestrationExecutionStore` replaces this without
    the coordinator or API layer changing.

    **Bounded, on both axes that could otherwise grow without limit:**
    - Per-execution event history is capped at `max_event_history` (oldest
      events are dropped first) -- a long-running or high-frequency
      execution can never grow this store without bound.
    - Each live SSE subscriber gets its own `asyncio.Queue(maxsize=
      subscriber_queue_size)`. `on_event` pushes with `put_nowait` and
      never blocks: a subscriber that falls behind that far is dropped
      from fan-out entirely (never buffered further) so one slow client
      can never slow down or backpressure real orchestration work. The
      dropped subscriber's queue receives one final `None` sentinel so its
      SSE read loop terminates cleanly instead of hanging forever waiting
      on a queue nothing will ever push to again; a client that reconnects
      always gets a full, correct replay from `get_events()` first (no
      event is ever lost from *history*, only from that one live queue).
    """

    def __init__(
        self,
        *,
        max_event_history: int = _DEFAULT_MAX_EVENT_HISTORY,
        subscriber_queue_size: int = _DEFAULT_SUBSCRIBER_QUEUE_SIZE,
    ) -> None:
        if max_event_history <= 0:
            raise ValueError("max_event_history must be positive")
        if subscriber_queue_size <= 0:
            raise ValueError("subscriber_queue_size must be positive")
        self._max_event_history = max_event_history
        self._subscriber_queue_size = subscriber_queue_size
        self._records: dict[str, OrchestrationExecutionRecord] = {}
        self._events: dict[str, list[OrchestrationEvent]] = {}
        self._subscribers: dict[str, list[asyncio.Queue[OrchestrationEvent | None]]] = {}
        self._lock = asyncio.Lock()

    async def create(self, execution_id: str) -> None:
        async with self._lock:
            now = datetime.now(UTC)
            self._records[execution_id] = OrchestrationExecutionRecord(
                execution_id=execution_id,
                status=OrchestrationExecutionStatus.ACCEPTED,
                created_at=now,
                updated_at=now,
            )
            self._events[execution_id] = []
            self._subscribers[execution_id] = []

    async def get(self, execution_id: str) -> OrchestrationExecutionRecord | None:
        async with self._lock:
            return self._records.get(execution_id)

    async def update_status(self, execution_id: str, status: OrchestrationExecutionStatus) -> None:
        async with self._lock:
            record = self._records.get(execution_id)
            if record is None:
                return
            self._records[execution_id] = replace(
                record, status=status, updated_at=datetime.now(UTC)
            )

    async def set_result(self, execution_id: str, result: OrchestrationResult) -> None:
        async with self._lock:
            record = self._records.get(execution_id)
            if record is None:
                return
            self._records[execution_id] = replace(
                record,
                status=OrchestrationExecutionStatus.COMPLETED,
                result=result,
                updated_at=datetime.now(UTC),
            )

    async def set_error(self, execution_id: str, error_summary: str) -> None:
        async with self._lock:
            record = self._records.get(execution_id)
            if record is None:
                return
            self._records[execution_id] = replace(
                record,
                status=OrchestrationExecutionStatus.FAILED,
                error_summary=error_summary,
                updated_at=datetime.now(UTC),
            )

    async def on_event(self, event: OrchestrationEvent) -> None:
        async with self._lock:
            history = self._events.setdefault(event.execution_id, [])
            history.append(event)
            if len(history) > self._max_event_history:
                del history[: len(history) - self._max_event_history]
            subscribers = list(self._subscribers.get(event.execution_id, ()))

        dead: list[asyncio.Queue[OrchestrationEvent | None]] = []
        for queue in subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(queue)

        if dead:
            async with self._lock:
                live = self._subscribers.get(event.execution_id, [])
                self._subscribers[event.execution_id] = [q for q in live if q not in dead]
            for queue in dead:
                logger.warning(
                    "orchestration_event_subscriber_dropped_slow_consumer execution_id=%s",
                    event.execution_id,
                )
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(None)

    async def get_events(
        self, execution_id: str, *, after_sequence: int = 0
    ) -> list[OrchestrationEvent]:
        async with self._lock:
            return [
                event
                for event in self._events.get(execution_id, ())
                if event.sequence > after_sequence
            ]

    @asynccontextmanager
    async def subscribe(
        self, execution_id: str
    ) -> AsyncIterator[asyncio.Queue[OrchestrationEvent | None]]:
        """Yield a bounded, per-connection queue that receives every event
        emitted for `execution_id` from this point forward -- never a
        polling loop. A `None` item on the queue means "stop reading":
        either the execution reached a terminal event, or (rare) this
        subscriber fell behind and was dropped (see `on_event`)."""
        queue: asyncio.Queue[OrchestrationEvent | None] = asyncio.Queue(
            maxsize=self._subscriber_queue_size
        )
        async with self._lock:
            self._subscribers.setdefault(execution_id, []).append(queue)
        try:
            yield queue
        finally:
            async with self._lock:
                live = self._subscribers.get(execution_id, [])
                self._subscribers[execution_id] = [q for q in live if q is not queue]


ServiceFactory = Callable[
    [OrchestrationRequest, OrchestrationEventSink, OrchestrationEventSequence],
    "tuple[EndToEndOrchestrationService, Callable[[], None]]",
]
"""Builds one fresh `EndToEndOrchestrationService` for one execution --
critically, with its own fresh DB session, never the short-lived,
request-scoped session an HTTP handler's own `Depends(get_db)` would give
it (that session closes when the HTTP response is sent, long before a
background execution finishes). Returns `(service, cleanup)`: the
coordinator always calls `cleanup()` in a `finally` block after
`orchestrate()` returns or raises, so the session is always closed exactly
once, regardless of outcome. See `app/api/deps.py` for the concrete
factory used by the API layer."""


class OrchestrationExecutionCoordinator:
    """Starts and tracks orchestration executions as isolated background
    tasks (Part 3). Never calls `service.orchestrate()` inline from a
    request handler -- `start()` schedules a background `asyncio.Task` and
    returns immediately."""

    def __init__(
        self, *, store: OrchestrationExecutionStore, service_factory: ServiceFactory
    ) -> None:
        self._store = store
        self._service_factory = service_factory
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def start(self, request: OrchestrationRequest) -> str:
        """Create the execution record, emit `execution.accepted`, and
        schedule the background orchestration task. Returns the
        `execution_id` (== `request.request_id`) immediately -- never
        awaits the orchestration itself."""
        execution_id = request.request_id
        await self._store.create(execution_id)

        sequence = OrchestrationEventSequence()
        accepted_sequence = sequence.next()
        await self._store.on_event(
            OrchestrationEvent(
                event_id=f"evt-{execution_id}-{accepted_sequence:04d}",
                execution_id=execution_id,
                sequence=accepted_sequence,
                event_type=OrchestrationEventType.EXECUTION_ACCEPTED,
                timestamp=datetime.now(UTC),
            )
        )

        task = asyncio.create_task(self._run(execution_id, request, sequence))
        self._tasks[execution_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(execution_id, None))
        return execution_id

    async def _run(
        self,
        execution_id: str,
        request: OrchestrationRequest,
        sequence: OrchestrationEventSequence,
    ) -> None:
        await self._store.update_status(execution_id, OrchestrationExecutionStatus.RUNNING)
        service, cleanup = self._service_factory(request, self._store, sequence)
        try:
            result = await service.orchestrate(request)
        except Exception as exc:  # noqa: BLE001 - job-level failure, mapped to a safe summary
            logger.exception("orchestration_execution_failed execution_id=%s", execution_id)
            await self._store.set_error(execution_id, _safe_error_summary(exc))
            failed_sequence = sequence.next()
            await self._store.on_event(
                OrchestrationEvent(
                    event_id=f"evt-{execution_id}-{failed_sequence:04d}",
                    execution_id=execution_id,
                    sequence=failed_sequence,
                    event_type=OrchestrationEventType.EXECUTION_FAILED,
                    timestamp=datetime.now(UTC),
                    status=type(exc).__name__,
                )
            )
            return
        finally:
            cleanup()
        # `service.orchestrate()` already emitted `execution.completed` as
        # its own last act (using this same shared `sequence`) -- the
        # coordinator only needs to persist the final result here.
        await self._store.set_result(execution_id, result)

    async def wait_for(self, execution_id: str, *, timeout: float | None = None) -> None:
        """Test/diagnostic helper only: await one execution's background
        task to finish. Production request handling never calls this --
        `POST` returns as soon as `start()` does, per Part 3."""
        task = self._tasks.get(execution_id)
        if task is None:
            return
        await asyncio.wait_for(asyncio.shield(task), timeout=timeout)


__all__ = [
    "InMemoryOrchestrationExecutionStore",
    "OrchestrationExecutionCoordinator",
    "OrchestrationExecutionRecord",
    "OrchestrationExecutionStatus",
    "OrchestrationExecutionStore",
    "ServiceFactory",
]
