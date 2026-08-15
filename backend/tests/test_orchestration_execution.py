"""Tests for `app.engine.orchestration.execution`: the bounded execution
job store + coordinator (Stage 8C.2, Part 3)."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.contracts.adapter import AgentDescriptor
from app.contracts.enums import AgentCapability, AgentStatus, RuntimeKind
from app.database.base import Base
from app.database.session import enable_sqlite_foreign_keys
from app.engine.orchestration.errors import OrchestrationExecutionAlreadyExistsError
from app.engine.orchestration.events import (
    OrchestrationEvent,
    OrchestrationEventSequence,
    OrchestrationEventSink,
    OrchestrationEventType,
)
from app.engine.orchestration.execution import (
    InMemoryOrchestrationExecutionStore,
    OrchestrationExecutionCoordinator,
    OrchestrationExecutionStatus,
)
from app.engine.orchestration.models import OrchestrationRequest
from app.engine.orchestration.runtime import StaticCandidateProvider
from app.engine.orchestration.service import EndToEndOrchestrationService
from app.engine.routing.availability import CandidateAgent

# Import models so create_all() registers every table (used by the "healthy"
# engine fixture below).
from app.models import audit_event as _audit_event  # noqa: F401,E402
from app.models import compensation_attempt as _compensation_attempt  # noqa: F401,E402
from app.models import step_attempt as _step_attempt  # noqa: F401,E402
from app.models import workflow as _workflow  # noqa: F401,E402
from app.models import workflow_step as _workflow_step  # noqa: F401,E402
from app.resilience.circuit_breaker import CircuitState
from tests.support.executors import RecordingExecutor
from tests.support.orchestration_api_fakes import build_test_service_factory
from tests.support.orchestration_fakes import RICH_SUCCESS_OUTPUT


def _make_event(
    execution_id: str, sequence: int, event_type: OrchestrationEventType
) -> OrchestrationEvent:
    return OrchestrationEvent(
        event_id=f"evt-{execution_id}-{sequence:04d}",
        execution_id=execution_id,
        sequence=sequence,
        event_type=event_type,
        timestamp=datetime.now(UTC),
    )


# --- InMemoryOrchestrationExecutionStore ------------------------------------


async def test_store_create_then_get_returns_accepted_record() -> None:
    store = InMemoryOrchestrationExecutionStore()
    await store.create("exec-1")
    record = await store.get("exec-1")
    assert record is not None
    assert record.status == OrchestrationExecutionStatus.ACCEPTED
    assert record.result is None


async def test_store_rejects_duplicate_id_without_destroying_existing_evidence() -> None:
    store = InMemoryOrchestrationExecutionStore()
    await store.create("exec-duplicate")
    await store.on_event(
        _make_event("exec-duplicate", 1, OrchestrationEventType.EXECUTION_ACCEPTED)
    )

    with pytest.raises(OrchestrationExecutionAlreadyExistsError):
        await store.create("exec-duplicate")

    events = await store.get_events("exec-duplicate")
    assert [event.sequence for event in events] == [1]


async def test_store_get_unknown_execution_returns_none() -> None:
    store = InMemoryOrchestrationExecutionStore()
    assert await store.get("does-not-exist") is None


async def test_store_update_status_transitions_record() -> None:
    store = InMemoryOrchestrationExecutionStore()
    await store.create("exec-1")
    await store.update_status("exec-1", OrchestrationExecutionStatus.RUNNING)
    record = await store.get("exec-1")
    assert record is not None
    assert record.status == OrchestrationExecutionStatus.RUNNING


async def test_store_set_error_records_safe_summary() -> None:
    store = InMemoryOrchestrationExecutionStore()
    await store.create("exec-1")
    await store.set_error("exec-1", "ValueError: an unexpected internal error occurred")
    record = await store.get("exec-1")
    assert record is not None
    assert record.status == OrchestrationExecutionStatus.FAILED
    assert record.error_summary == "ValueError: an unexpected internal error occurred"


async def test_store_on_event_appends_and_get_events_filters_by_sequence() -> None:
    store = InMemoryOrchestrationExecutionStore()
    await store.create("exec-1")
    for i in range(1, 4):
        await store.on_event(_make_event("exec-1", i, OrchestrationEventType.STEP_STARTED))

    all_events = await store.get_events("exec-1")
    assert [e.sequence for e in all_events] == [1, 2, 3]

    after_one = await store.get_events("exec-1", after_sequence=1)
    assert [e.sequence for e in after_one] == [2, 3]


async def test_store_event_history_is_bounded() -> None:
    store = InMemoryOrchestrationExecutionStore(max_event_history=5)
    await store.create("exec-1")
    for i in range(1, 11):
        await store.on_event(_make_event("exec-1", i, OrchestrationEventType.STEP_STARTED))

    events = await store.get_events("exec-1")
    assert len(events) == 5
    assert [e.sequence for e in events] == [6, 7, 8, 9, 10]


async def test_store_events_are_isolated_per_execution() -> None:
    store = InMemoryOrchestrationExecutionStore()
    await store.create("exec-a")
    await store.create("exec-b")
    await store.on_event(_make_event("exec-a", 1, OrchestrationEventType.EXECUTION_STARTED))
    await store.on_event(_make_event("exec-b", 1, OrchestrationEventType.EXECUTION_STARTED))
    await store.on_event(_make_event("exec-a", 2, OrchestrationEventType.EXECUTION_COMPLETED))

    a_events = await store.get_events("exec-a")
    b_events = await store.get_events("exec-b")
    assert len(a_events) == 2
    assert len(b_events) == 1
    assert all(e.execution_id == "exec-a" for e in a_events)
    assert all(e.execution_id == "exec-b" for e in b_events)


async def test_store_subscriber_receives_live_events() -> None:
    store = InMemoryOrchestrationExecutionStore()
    await store.create("exec-1")

    async with store.subscribe("exec-1") as queue:
        await store.on_event(_make_event("exec-1", 1, OrchestrationEventType.EXECUTION_STARTED))
        received = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert received is not None
        assert received.sequence == 1


async def test_store_subscriber_stops_receiving_after_unsubscribe() -> None:
    store = InMemoryOrchestrationExecutionStore()
    await store.create("exec-1")

    async with store.subscribe("exec-1") as queue:
        pass  # unsubscribed immediately on context exit

    await store.on_event(_make_event("exec-1", 1, OrchestrationEventType.EXECUTION_STARTED))
    assert queue.empty()


async def test_store_slow_subscriber_is_dropped_not_blocking() -> None:
    """A subscriber whose queue fills up must be dropped from fan-out
    (never block `on_event`, never grow without bound) and receive a
    terminating `None` sentinel."""
    store = InMemoryOrchestrationExecutionStore(subscriber_queue_size=2)
    await store.create("exec-1")

    async with store.subscribe("exec-1") as queue:
        # Fill the bounded queue without draining it.
        for i in range(1, 3):
            await store.on_event(_make_event("exec-1", i, OrchestrationEventType.STEP_STARTED))
        assert queue.full()

        # One more event overflows the queue -- must not raise/hang here.
        await store.on_event(_make_event("exec-1", 3, OrchestrationEventType.STEP_COMPLETED))

        # The dropped subscriber gets a terminal `None` appended after its
        # two buffered real events.
        first = await asyncio.wait_for(queue.get(), timeout=1.0)
        second = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert first is not None and second is not None
        # Queue was full (maxsize=2) so the sentinel could not also fit;
        # confirm the subscriber was actually removed from fan-out instead.
        await store.on_event(_make_event("exec-1", 4, OrchestrationEventType.STEP_STARTED))
        assert queue.empty()


# --- OrchestrationExecutionCoordinator --------------------------------------


@pytest.fixture
def healthy_db_engine() -> Engine:
    # `StaticPool` is required, not optional, for an in-memory SQLite
    # engine used across threads: without it, each connection checkout
    # opens its own private `:memory:` database, so the coordinator's
    # orchestration -- now offloaded to a worker thread via
    # `asyncio.to_thread` (Stage 8C.3 usability hardening, so a real
    # long-running agent call can no longer freeze the whole event loop)
    # -- would see a blank database missing every table `create_all()`
    # just created on this thread.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(bind=engine)
    return engine


def _request(request_id: str, *, agent_type: str = "dyn-agent-1") -> OrchestrationRequest:
    return OrchestrationRequest(
        request_id=request_id,
        goal="Implement user authentication with tests",
        available_agent_types=[agent_type],
    )


async def test_coordinator_start_returns_execution_id_and_completes(
    healthy_db_engine: Engine,
) -> None:
    factory, manager, _registry = build_test_service_factory(
        db_engine=healthy_db_engine,
        agent_type="dyn-agent-1",
        executor=RecordingExecutor(output=dict(RICH_SUCCESS_OUTPUT)),
    )
    store = InMemoryOrchestrationExecutionStore()
    coordinator = OrchestrationExecutionCoordinator(store=store, service_factory=factory)

    execution_id = await coordinator.start(_request("exec-coord-1", agent_type="dyn-agent-1"))
    assert execution_id == "exec-coord-1"

    await coordinator.wait_for(execution_id, timeout=5.0)
    record = await store.get(execution_id)
    assert record is not None
    assert record.status == OrchestrationExecutionStatus.COMPLETED
    assert record.result is not None
    assert record.result.outcome.value == "verified_success"
    assert len(manager.calls) == 1


async def test_coordinator_emits_accepted_event_first(healthy_db_engine: Engine) -> None:
    factory, _manager, _registry = build_test_service_factory(
        db_engine=healthy_db_engine, agent_type="dyn-agent-1"
    )
    store = InMemoryOrchestrationExecutionStore()
    coordinator = OrchestrationExecutionCoordinator(store=store, service_factory=factory)

    execution_id = await coordinator.start(_request("exec-coord-2", agent_type="dyn-agent-1"))
    await coordinator.wait_for(execution_id, timeout=5.0)

    events = await store.get_events(execution_id)
    assert events[0].event_type == OrchestrationEventType.EXECUTION_ACCEPTED
    assert events[0].sequence == 1
    # Every subsequent event continues the SAME monotonic counter.
    assert [e.sequence for e in events] == list(range(1, len(events) + 1))


async def test_coordinator_isolates_concurrent_executions(healthy_db_engine: Engine) -> None:
    factory, manager, _registry = build_test_service_factory(
        db_engine=healthy_db_engine, agent_type="dyn-agent-1"
    )
    store = InMemoryOrchestrationExecutionStore()
    coordinator = OrchestrationExecutionCoordinator(store=store, service_factory=factory)

    id_a = await coordinator.start(_request("exec-conc-a", agent_type="dyn-agent-1"))
    id_b = await coordinator.start(_request("exec-conc-b", agent_type="dyn-agent-1"))
    await coordinator.wait_for(id_a, timeout=5.0)
    await coordinator.wait_for(id_b, timeout=5.0)

    events_a = await store.get_events(id_a)
    events_b = await store.get_events(id_b)
    assert all(e.execution_id == id_a for e in events_a)
    assert all(e.execution_id == id_b for e in events_b)
    assert len(manager.calls) == 2
    assert {call.request_id for call in manager.calls} == {id_a, id_b}


async def test_coordinator_rejects_simultaneous_duplicate_execution_ids(
    healthy_db_engine: Engine,
) -> None:
    factory, manager, _registry = build_test_service_factory(
        db_engine=healthy_db_engine, agent_type="dyn-agent-1"
    )
    store = InMemoryOrchestrationExecutionStore()
    coordinator = OrchestrationExecutionCoordinator(store=store, service_factory=factory)
    request = _request("exec-same", agent_type="dyn-agent-1")

    results = await asyncio.gather(
        coordinator.start(request), coordinator.start(request), return_exceptions=True
    )
    assert sum(result == "exec-same" for result in results) == 1
    assert (
        sum(isinstance(result, OrchestrationExecutionAlreadyExistsError) for result in results) == 1
    )

    await coordinator.wait_for("exec-same", timeout=5.0)
    assert len(manager.calls) == 1
    events = await store.get_events("exec-same")
    assert events[0].event_type == OrchestrationEventType.EXECUTION_ACCEPTED
    assert len([event for event in events if event.sequence == 1]) == 1


async def test_coordinator_factory_failure_reaches_terminal_failed_state() -> None:
    def broken_factory(
        request: OrchestrationRequest,
        event_sink: OrchestrationEventSink,
        event_sequence: OrchestrationEventSequence,
    ) -> tuple[EndToEndOrchestrationService, Callable[[], None]]:
        del request, event_sink, event_sequence
        raise RuntimeError("provider bootstrap secret must not leak")

    store = InMemoryOrchestrationExecutionStore()
    coordinator = OrchestrationExecutionCoordinator(store=store, service_factory=broken_factory)

    execution_id = await coordinator.start(_request("exec-factory-failure"))
    await coordinator.wait_for(execution_id, timeout=5.0)

    record = await store.get(execution_id)
    assert record is not None
    assert record.status == OrchestrationExecutionStatus.FAILED
    assert record.error_summary == "RuntimeError: an unexpected internal error occurred"
    assert "secret" not in record.error_summary
    events = await store.get_events(execution_id)
    assert events[-1].event_type == OrchestrationEventType.EXECUTION_FAILED


async def test_coordinator_maps_persistence_failure_to_failed_status() -> None:
    """No tables created on this engine -- `_phase_d_execute` genuinely
    fails at the persistence layer, so `orchestrate()` raises
    `OrchestrationPersistenceError` (a recognized, safe-to-summarize type)."""
    broken_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    factory, _manager, _registry = build_test_service_factory(
        db_engine=broken_engine, agent_type="dyn-agent-1"
    )
    store = InMemoryOrchestrationExecutionStore()
    coordinator = OrchestrationExecutionCoordinator(store=store, service_factory=factory)

    execution_id = await coordinator.start(_request("exec-fail-1", agent_type="dyn-agent-1"))
    await coordinator.wait_for(execution_id, timeout=5.0)

    record = await store.get(execution_id)
    assert record is not None
    assert record.status == OrchestrationExecutionStatus.FAILED
    assert record.error_summary is not None
    assert record.error_summary.startswith("OrchestrationPersistenceError:")

    events = await store.get_events(execution_id)
    assert events[-1].event_type == OrchestrationEventType.EXECUTION_FAILED


async def test_coordinator_unrecognized_exception_never_leaks_raw_message(
    healthy_db_engine: Engine,
) -> None:
    """An unrecognized exception type (never explicitly allowlisted as
    safe) must fall back to a fully generic summary -- never `str(exc)`,
    since an unexpected exception could in principle carry provider or
    runtime content."""

    class _BoomManagerModel:
        def identifier(self) -> str:
            return "boom-manager"

        async def propose(self, request: object) -> object:
            raise ValueError("super secret internal detail that must never leak")

    factory, _manager, registry = build_test_service_factory(
        db_engine=healthy_db_engine, agent_type="dyn-agent-1"
    )

    def broken_factory(
        request: OrchestrationRequest,
        event_sink: OrchestrationEventSink,
        event_sequence: OrchestrationEventSequence,
    ) -> tuple[EndToEndOrchestrationService, Callable[[], None]]:
        session_factory = sessionmaker(
            bind=healthy_db_engine, autoflush=False, expire_on_commit=False
        )
        db = session_factory()
        descriptor = AgentDescriptor(
            agent_type="dyn-agent-1",
            display_name="dyn",
            runtime_kind=RuntimeKind.AGENT_CLI,
            capabilities=list(AgentCapability),
        )
        candidate_provider = StaticCandidateProvider(
            agents=(
                CandidateAgent(
                    descriptor=descriptor,
                    status=AgentStatus.AVAILABLE,
                    circuit_state=CircuitState.CLOSED,
                ),
            )
        )
        service = EndToEndOrchestrationService(
            db=db,
            registry=registry,
            candidate_provider=candidate_provider,
            manager_model=_BoomManagerModel(),  # type: ignore[arg-type]
            event_sink=event_sink,
            event_sequence=event_sequence,
        )
        return service, db.close

    store = InMemoryOrchestrationExecutionStore()
    coordinator = OrchestrationExecutionCoordinator(store=store, service_factory=broken_factory)

    execution_id = await coordinator.start(_request("exec-boom-1", agent_type="dyn-agent-1"))
    await coordinator.wait_for(execution_id, timeout=5.0)

    record = await store.get(execution_id)
    assert record is not None
    assert record.status == OrchestrationExecutionStatus.FAILED
    assert record.error_summary is not None
    assert "super secret internal detail" not in record.error_summary
    assert record.error_summary == "ValueError: an unexpected internal error occurred"
