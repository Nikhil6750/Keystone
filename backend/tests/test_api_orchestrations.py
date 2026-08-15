"""Stage 8C.2 API tests: `POST/GET /api/v1/orchestrations` + SSE events.

Entirely offline -- every Manager/executor is a deterministic test double
(`EchoingFakeManagerModel`, `RecordingExecutor`); nothing here makes a
network call, reads a credential, or launches a subprocess. Uses the real
FastAPI app (`app.main.app`), the real `EndToEndOrchestrationService`,
Planner, Router, WorkflowEngine, Verification, and Learning -- only the
Manager and the dynamic worker's execution are faked (Part 17).
"""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.api.deps import get_orchestration_execution_coordinator, get_orchestration_execution_store
from app.database.base import Base
from app.database.session import enable_sqlite_foreign_keys
from app.engine.orchestration.execution import (
    InMemoryOrchestrationExecutionStore,
    OrchestrationExecutionCoordinator,
)
from app.main import app

# Import models so create_all() registers every table.
from app.models import audit_event as _audit_event  # noqa: F401,E402
from app.models import compensation_attempt as _compensation_attempt  # noqa: F401,E402
from app.models import step_attempt as _step_attempt  # noqa: F401,E402
from app.models import workflow as _workflow  # noqa: F401,E402
from app.models import workflow_step as _workflow_step  # noqa: F401,E402
from tests.support.executors import RecordingExecutor
from tests.support.orchestration_api_fakes import (
    build_test_service_factory,
)
from tests.support.orchestration_fakes import RICH_SUCCESS_OUTPUT

_TERMINAL_EVENT_TYPES = {"execution.completed", "execution.failed", "execution.cancelled"}


@pytest.fixture
def api_db_engine() -> Engine:
    # `StaticPool` is required for an in-memory SQLite engine used across
    # threads -- see the identical fixture/comment in
    # `test_orchestration_execution.py::healthy_db_engine`.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(bind=engine)
    return engine


@asynccontextmanager
async def _orchestration_client(
    db_engine: Engine,
    *,
    agent_type: str = "api-test-agent",
    executor: RecordingExecutor | None = None,
    manager: object | None = None,
) -> AsyncIterator[
    tuple[AsyncClient, InMemoryOrchestrationExecutionStore, OrchestrationExecutionCoordinator]
]:
    """Builds a real ASGI test client for `app.main.app` wired to isolated,
    offline test doubles -- mirrors `tests/conftest.py::client`'s override
    pattern exactly, scoped to just the orchestration dependencies."""
    factory, echo_manager, _registry = build_test_service_factory(
        db_engine=db_engine,
        agent_type=agent_type,
        executor=executor or RecordingExecutor(output=dict(RICH_SUCCESS_OUTPUT)),
    )
    if manager is not None:
        # Swap in a caller-supplied manager (e.g. to test fallback) by
        # rebuilding the factory's closure target directly.
        from sqlalchemy.orm import sessionmaker

        from app.contracts.adapter import AgentDescriptor
        from app.contracts.enums import AgentCapability, AgentStatus, RuntimeKind
        from app.engine.orchestration.runtime import StaticCandidateProvider
        from app.engine.orchestration.service import EndToEndOrchestrationService
        from app.engine.routing.availability import CandidateAgent
        from app.resilience.circuit_breaker import CircuitBreakerRegistry, CircuitState
        from app.resilience.retry import RetryPolicy

        session_factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
        registry = _registry
        descriptor = AgentDescriptor(
            agent_type=agent_type,
            display_name=agent_type,
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
        circuit_breakers = CircuitBreakerRegistry(
            failure_threshold=3, recovery_timeout_seconds=30.0
        )
        retry_policy = RetryPolicy(
            base_delay_seconds=0.01, max_delay_seconds=0.05, jitter_ratio=0.0
        )

        def factory(request, event_sink, event_sequence):  # type: ignore[no-untyped-def]
            db = session_factory()
            service = EndToEndOrchestrationService(
                db=db,
                registry=registry,
                candidate_provider=candidate_provider,
                manager_model=manager,
                circuit_breakers=circuit_breakers,
                retry_policy=retry_policy,
                event_sink=event_sink,
                event_sequence=event_sequence,
            )
            return service, db.close

    store = InMemoryOrchestrationExecutionStore()
    coordinator = OrchestrationExecutionCoordinator(store=store, service_factory=factory)

    app.dependency_overrides[get_orchestration_execution_store] = lambda: store
    app.dependency_overrides[get_orchestration_execution_coordinator] = lambda: coordinator
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as async_client:
            yield async_client, store, coordinator
    finally:
        app.dependency_overrides.pop(get_orchestration_execution_store, None)
        app.dependency_overrides.pop(get_orchestration_execution_coordinator, None)


def _parse_sse_frame(frame: str) -> dict:
    event_id = None
    event_type = None
    data = None
    for line in frame.splitlines():
        if line.startswith("id: "):
            event_id = line[len("id: ") :]
        elif line.startswith("event: "):
            event_type = line[len("event: ") :]
        elif line.startswith("data: "):
            data = json.loads(line[len("data: ") :])
    return {"id": event_id, "event": event_type, "data": data}


async def _read_sse_events(client: AsyncClient, url: str, *, max_events: int = 200) -> list[dict]:
    events: list[dict] = []

    async def _read() -> None:
        async with client.stream("GET", url) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            buffer = ""
            async for chunk in response.aiter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    frame, buffer = buffer.split("\n\n", 1)
                    if not frame.strip() or frame.startswith(":"):
                        continue
                    event = _parse_sse_frame(frame)
                    events.append(event)
                    if event["event"] in _TERMINAL_EVENT_TYPES or len(events) >= max_events:
                        return

    await asyncio.wait_for(_read(), timeout=10.0)
    return events


GOAL = "Implement user authentication with tests"


# --- POST -------------------------------------------------------------------


async def test_post_returns_202_quickly(api_db_engine: Engine) -> None:
    async with _orchestration_client(api_db_engine) as (client, _store, _coordinator):
        response = await asyncio.wait_for(
            client.post(
                "/api/v1/orchestrations",
                json={"goal": GOAL, "available_agent_types": ["api-test-agent"]},
            ),
            timeout=2.0,
        )
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "accepted"
        assert body["execution_id"]
        assert body["events_url"]
        assert body["result_url"]


async def test_post_creates_unique_execution_ids(api_db_engine: Engine) -> None:
    async with _orchestration_client(api_db_engine) as (client, _store, _coordinator):
        r1 = await client.post(
            "/api/v1/orchestrations",
            json={"goal": GOAL, "available_agent_types": ["api-test-agent"]},
        )
        r2 = await client.post(
            "/api/v1/orchestrations",
            json={"goal": GOAL, "available_agent_types": ["api-test-agent"]},
        )
        assert r1.json()["execution_id"] != r2.json()["execution_id"]


async def test_post_rejects_blank_goal(api_db_engine: Engine) -> None:
    async with _orchestration_client(api_db_engine) as (client, _store, _coordinator):
        response = await client.post("/api/v1/orchestrations", json={"goal": "   "})
        assert response.status_code == 422


async def test_post_rejects_unknown_fields(api_db_engine: Engine) -> None:
    async with _orchestration_client(api_db_engine) as (client, _store, _coordinator):
        response = await client.post(
            "/api/v1/orchestrations", json={"goal": GOAL, "api_key": "sk-should-be-rejected"}
        )
        assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"goal": "x" * 4001},
        {"goal": GOAL, "request_id": "x" * 201},
        {"goal": GOAL, "request_id": "unsafe/id"},
        {"goal": GOAL, "workspace_root": "relative/path"},
        {"goal": GOAL, "available_agent_types": ["agent"] * 51},
        {"goal": GOAL, "available_agent_types": ["agent", "agent"]},
    ],
)
async def test_post_rejects_malformed_or_unbounded_inputs_before_scheduling(
    api_db_engine: Engine, payload: dict[str, object]
) -> None:
    async with _orchestration_client(api_db_engine) as (client, store, _coordinator):
        response = await client.post("/api/v1/orchestrations", json=payload)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_REQUEST"
        assert await store.get(str(payload.get("request_id", ""))) is None


async def test_post_duplicate_request_id_returns_409_and_runs_once(
    api_db_engine: Engine,
) -> None:
    executor = RecordingExecutor(output=dict(RICH_SUCCESS_OUTPUT))
    async with _orchestration_client(api_db_engine, executor=executor) as (
        client,
        _store,
        coordinator,
    ):
        payload = {
            "goal": GOAL,
            "request_id": "client-idempotency-key",
            "available_agent_types": ["api-test-agent"],
        }
        first, duplicate = await asyncio.gather(
            client.post("/api/v1/orchestrations", json=payload),
            client.post("/api/v1/orchestrations", json=payload),
        )
        assert sorted((first.status_code, duplicate.status_code)) == [202, 409]
        conflict = first if first.status_code == 409 else duplicate
        assert conflict.json()["error"]["code"] == "ORCHESTRATION_EXECUTION_EXISTS"

        await coordinator.wait_for("client-idempotency-key", timeout=5.0)
        assert len({call.workflow_id for call in executor.calls}) == 1


async def test_orchestration_runs_asynchronously_not_inline(api_db_engine: Engine) -> None:
    """POST must not block until the pipeline finishes -- the execution
    should still be running (or, at worst, not yet observed as completed
    at the instant POST returns) immediately after the response."""
    async with _orchestration_client(api_db_engine) as (client, store, _coordinator):
        response = await client.post(
            "/api/v1/orchestrations",
            json={"goal": GOAL, "available_agent_types": ["api-test-agent"]},
        )
        execution_id = response.json()["execution_id"]
        record = await store.get(execution_id)
        assert record is not None
        assert record.status in ("accepted", "running")


# --- GET status/result -------------------------------------------------------


async def test_get_status_while_running_then_completed(api_db_engine: Engine) -> None:
    async with _orchestration_client(api_db_engine) as (client, _store, coordinator):
        response = await client.post(
            "/api/v1/orchestrations",
            json={"goal": GOAL, "available_agent_types": ["api-test-agent"]},
        )
        execution_id = response.json()["execution_id"]

        status_response = await client.get(f"/api/v1/orchestrations/{execution_id}")
        assert status_response.status_code == 200
        assert status_response.json()["job_status"] in ("accepted", "running", "completed")

        await coordinator.wait_for(execution_id, timeout=5.0)

        final_response = await client.get(f"/api/v1/orchestrations/{execution_id}")
        body = final_response.json()
        assert body["job_status"] == "completed"
        assert body["orchestration_outcome"] == "verified_success"
        assert body["verification_status"] == "passed"
        assert body["retrieval_feedback_recorded"] is False  # no knowledge index wired in tests


async def test_get_unknown_execution_returns_404(api_db_engine: Engine) -> None:
    async with _orchestration_client(api_db_engine) as (client, _store, _coordinator):
        response = await client.get("/api/v1/orchestrations/does-not-exist")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "ORCHESTRATION_EXECUTION_NOT_FOUND"


async def test_events_for_unknown_execution_returns_404(api_db_engine: Engine) -> None:
    async with _orchestration_client(api_db_engine) as (client, _store, _coordinator):
        response = await client.get("/api/v1/orchestrations/does-not-exist/events")
        assert response.status_code == 404


async def test_no_eligible_route_is_a_safe_terminal_outcome_not_a_5xx(
    api_db_engine: Engine,
) -> None:
    """No executor registered for the client's requested agent type ->
    business `NO_ELIGIBLE_ROUTE`, a normal 200 status read, never an HTTP
    5xx (Part 13/19)."""
    async with _orchestration_client(api_db_engine, agent_type="api-test-agent") as (
        client,
        _store,
        coordinator,
    ):
        response = await client.post(
            "/api/v1/orchestrations",
            json={"goal": GOAL, "available_agent_types": ["some-other-unregistered-agent"]},
        )
        execution_id = response.json()["execution_id"]
        await coordinator.wait_for(execution_id, timeout=5.0)

        status_response = await client.get(f"/api/v1/orchestrations/{execution_id}")
        assert status_response.status_code == 200
        body = status_response.json()
        assert body["job_status"] == "completed"
        assert body["orchestration_outcome"] == "no_eligible_route"


# --- SSE ----------------------------------------------------------------------


async def test_sse_content_type_and_full_event_sequence(api_db_engine: Engine) -> None:
    async with _orchestration_client(api_db_engine) as (client, _store, coordinator):
        response = await client.post(
            "/api/v1/orchestrations",
            json={"goal": GOAL, "available_agent_types": ["api-test-agent"]},
        )
        execution_id = response.json()["execution_id"]
        await coordinator.wait_for(execution_id, timeout=5.0)

        events = await _read_sse_events(client, f"/api/v1/orchestrations/{execution_id}/events")

        assert events[0]["event"] == "execution.accepted"
        assert events[-1]["event"] == "execution.completed"
        sequences = [e["data"]["sequence"] for e in events]
        assert sequences == sorted(sequences)
        assert len(set(sequences)) == len(sequences)


async def test_terminal_event_emitted_exactly_once_and_stream_terminates(
    api_db_engine: Engine,
) -> None:
    async with _orchestration_client(api_db_engine) as (client, _store, coordinator):
        response = await client.post(
            "/api/v1/orchestrations",
            json={"goal": GOAL, "available_agent_types": ["api-test-agent"]},
        )
        execution_id = response.json()["execution_id"]
        await coordinator.wait_for(execution_id, timeout=5.0)

        events = await _read_sse_events(client, f"/api/v1/orchestrations/{execution_id}/events")
        terminal = [e for e in events if e["event"] in _TERMINAL_EVENT_TYPES]
        assert len(terminal) == 1


async def test_late_subscriber_receives_full_replay(api_db_engine: Engine) -> None:
    """Connecting to SSE only after the execution already finished must
    still deliver the complete event history in order (Part 10)."""
    async with _orchestration_client(api_db_engine) as (client, _store, coordinator):
        response = await client.post(
            "/api/v1/orchestrations",
            json={"goal": GOAL, "available_agent_types": ["api-test-agent"]},
        )
        execution_id = response.json()["execution_id"]
        await coordinator.wait_for(execution_id, timeout=5.0)  # finishes before SSE connects

        events = await _read_sse_events(client, f"/api/v1/orchestrations/{execution_id}/events")
        assert events[0]["event"] == "execution.accepted"
        assert len(events) > 5


async def test_reconnect_does_not_rerun_manager_or_workflow(api_db_engine: Engine) -> None:
    async with _orchestration_client(api_db_engine) as (client, _store, coordinator):
        response = await client.post(
            "/api/v1/orchestrations",
            json={"goal": GOAL, "available_agent_types": ["api-test-agent"]},
        )
        execution_id = response.json()["execution_id"]
        await coordinator.wait_for(execution_id, timeout=5.0)

        events_url = f"/api/v1/orchestrations/{execution_id}/events"
        first = await _read_sse_events(client, events_url)
        second = await _read_sse_events(client, events_url)
        assert [e["event"] for e in first] == [e["event"] for e in second]

        status = await client.get(f"/api/v1/orchestrations/{execution_id}")
        workflow_ids = {
            e["data"]["workflow_id"] for e in first if e["data"]["workflow_id"] is not None
        }
        assert len(workflow_ids) == 1
        assert status.json()["workflow_id"] in workflow_ids


async def test_live_sse_connection_observes_phase_events_as_they_happen(
    api_db_engine: Engine,
) -> None:
    """Part 17's high-value flow: connect SSE *before* the execution
    finishes and observe genuinely live-pushed events, not just a replay."""
    async with _orchestration_client(api_db_engine) as (client, store, coordinator):
        response = await client.post(
            "/api/v1/orchestrations",
            json={"goal": GOAL, "available_agent_types": ["api-test-agent"]},
        )
        execution_id = response.json()["execution_id"]

        events = await _read_sse_events(client, f"/api/v1/orchestrations/{execution_id}/events")
        await coordinator.wait_for(execution_id, timeout=5.0)

        assert events[0]["event"] == "execution.accepted"
        assert events[-1]["event"] == "execution.completed"
        record = await store.get(execution_id)
        assert record is not None
        assert record.result is not None
        assert record.result.outcome.value == "verified_success"


# --- Manager / dynamic agents -------------------------------------------------


async def test_manager_called_exactly_once_per_execution(api_db_engine: Engine) -> None:
    async with _orchestration_client(api_db_engine) as (client, _store, coordinator):
        response = await client.post(
            "/api/v1/orchestrations",
            json={"goal": GOAL, "available_agent_types": ["api-test-agent"]},
        )
        execution_id = response.json()["execution_id"]
        await coordinator.wait_for(execution_id, timeout=5.0)
        # Reading events/status afterward must never trigger another call.
        await _read_sse_events(client, f"/api/v1/orchestrations/{execution_id}/events")
        await client.get(f"/api/v1/orchestrations/{execution_id}")

        events = await _read_sse_events(client, f"/api/v1/orchestrations/{execution_id}/events")
        manager_completed = [e for e in events if e["event"] == "manager.completed"]
        assert len(manager_completed) == 1


@pytest.mark.parametrize(
    "agent_id",
    ["openrouter-qwen-coder", "company-review-agent", "local-test-agent", "user-qwen-coder-1"],
)
async def test_dynamic_arbitrary_agent_id_is_supported_end_to_end(
    api_db_engine: Engine, agent_id: str
) -> None:
    """Proves no fixed agent-identity assumption anywhere in the request
    schema, routing event, or final result (Part 15)."""
    async with _orchestration_client(api_db_engine, agent_type=agent_id) as (
        client,
        _store,
        coordinator,
    ):
        response = await client.post(
            "/api/v1/orchestrations",
            json={"goal": GOAL, "available_agent_types": [agent_id]},
        )
        assert response.status_code == 202
        execution_id = response.json()["execution_id"]
        await coordinator.wait_for(execution_id, timeout=5.0)

        events = await _read_sse_events(client, f"/api/v1/orchestrations/{execution_id}/events")
        routing_events = [e for e in events if e["event"] == "routing.task_selected"]
        assert routing_events
        assert all(e["data"]["agent_id"] == agent_id for e in routing_events)

        status = await client.get(f"/api/v1/orchestrations/{execution_id}")
        assert agent_id in status.json()["selected_agent_types"]


async def test_manager_fallback_event_emitted_when_manager_unavailable(
    api_db_engine: Engine,
) -> None:
    from app.engine.manager.errors import ManagerUnavailableError

    class _AlwaysUnavailableManager:
        def identifier(self) -> str:
            return "always-unavailable"

        async def propose(self, request: object) -> object:
            raise ManagerUnavailableError("simulated: manager unavailable")

    async with _orchestration_client(
        api_db_engine, agent_type="api-test-agent", manager=_AlwaysUnavailableManager()
    ) as (client, _store, coordinator):
        response = await client.post(
            "/api/v1/orchestrations",
            json={"goal": GOAL, "available_agent_types": ["api-test-agent"]},
        )
        execution_id = response.json()["execution_id"]
        await coordinator.wait_for(execution_id, timeout=5.0)

        events = await _read_sse_events(client, f"/api/v1/orchestrations/{execution_id}/events")
        assert any(e["event"] == "manager.fallback" for e in events)
        status = await client.get(f"/api/v1/orchestrations/{execution_id}")
        assert status.json()["job_status"] == "completed"


# --- Workflow / verification / recovery / learning / retrieval feedback ------


async def test_full_event_taxonomy_for_a_verified_success_run(api_db_engine: Engine) -> None:
    async with _orchestration_client(api_db_engine) as (client, _store, coordinator):
        response = await client.post(
            "/api/v1/orchestrations",
            json={"goal": GOAL, "available_agent_types": ["api-test-agent"]},
        )
        execution_id = response.json()["execution_id"]
        await coordinator.wait_for(execution_id, timeout=5.0)

        events = await _read_sse_events(client, f"/api/v1/orchestrations/{execution_id}/events")
        types = [e["event"] for e in events]

        assert "workflow.created" in types
        assert "workflow.started" in types
        assert types.count("step.started") == types.count("step.completed")
        assert "step.failed" not in types
        assert "verification.started" in types
        assert "verification.completed" in types

        verification_completed = next(e for e in events if e["event"] == "verification.completed")
        assert verification_completed["data"]["verification_status"] == "passed"

        assert "recovery.started" not in types  # no recovery needed on first-try success

        learning_event_count = (await client.get(f"/api/v1/orchestrations/{execution_id}")).json()[
            "learning_event_count"
        ]
        assert learning_event_count is not None and learning_event_count > 0

        retrieval_feedback = next(e for e in events if e["event"] == "retrieval_feedback.completed")
        assert retrieval_feedback["data"]["status"] == "not_recorded"  # no knowledge index wired


async def test_verification_failure_and_recovery_events(api_db_engine: Engine) -> None:
    """An executor whose output carries none of the evidence keys any
    evaluator needs deterministically yields INCONCLUSIVE -> bounded
    recovery -> RECOVERY_EXHAUSTED (see the certified Stage 8C.1 live
    diagnostic this exact scenario was traced from)."""
    async with _orchestration_client(api_db_engine, executor=RecordingExecutor(output={})) as (
        client,
        _store,
        coordinator,
    ):
        response = await client.post(
            "/api/v1/orchestrations",
            json={"goal": GOAL, "available_agent_types": ["api-test-agent"]},
        )
        execution_id = response.json()["execution_id"]
        await coordinator.wait_for(execution_id, timeout=5.0)

        events = await _read_sse_events(client, f"/api/v1/orchestrations/{execution_id}/events")
        types = [e["event"] for e in events]
        assert "recovery.started" in types
        assert "recovery.exhausted" in types

        verification_completed = [e for e in events if e["event"] == "verification.completed"]
        assert verification_completed[-1]["data"]["verification_status"] == "inconclusive"

        status = await client.get(f"/api/v1/orchestrations/{execution_id}")
        body = status.json()
        assert body["job_status"] == "completed"  # job succeeded; business outcome did not
        assert body["orchestration_outcome"] == "recovery_exhausted"
        assert body["retrieval_feedback_recorded"] is False


# --- Security: no CoT / secrets / raw output ---------------------------------


async def test_serialized_events_never_contain_forbidden_content(api_db_engine: Engine) -> None:
    async with _orchestration_client(api_db_engine) as (client, _store, coordinator):
        response = await client.post(
            "/api/v1/orchestrations",
            json={"goal": GOAL, "available_agent_types": ["api-test-agent"]},
        )
        execution_id = response.json()["execution_id"]
        await coordinator.wait_for(execution_id, timeout=5.0)

        events = await _read_sse_events(client, f"/api/v1/orchestrations/{execution_id}/events")
        raw_text = json.dumps(events).lower()
        for forbidden in (
            "reasoning_content",
            "chain_of_thought",
            "authorization",
            "api_key",
            "sk-",
            "bearer ",
            "traceback",
            "password",
        ):
            assert forbidden not in raw_text


async def test_concurrent_executions_are_isolated_at_the_api_layer(api_db_engine: Engine) -> None:
    async with _orchestration_client(api_db_engine) as (client, _store, coordinator):
        r1 = await client.post(
            "/api/v1/orchestrations",
            json={"goal": GOAL, "available_agent_types": ["api-test-agent"]},
        )
        r2 = await client.post(
            "/api/v1/orchestrations",
            json={"goal": GOAL, "available_agent_types": ["api-test-agent"]},
        )
        id1, id2 = r1.json()["execution_id"], r2.json()["execution_id"]
        assert id1 != id2
        await coordinator.wait_for(id1, timeout=5.0)
        await coordinator.wait_for(id2, timeout=5.0)

        events1 = await _read_sse_events(client, f"/api/v1/orchestrations/{id1}/events")
        events2 = await _read_sse_events(client, f"/api/v1/orchestrations/{id2}/events")
        exec_ids_1 = {e["data"]["execution_id"] for e in events1}
        exec_ids_2 = {e["data"]["execution_id"] for e in events2}
        assert exec_ids_1 == {id1}
        assert exec_ids_2 == {id2}


async def test_api_does_not_instantiate_provider_specific_manager_directly() -> None:
    """Static check: the route module never imports a concrete
    provider-specific ManagerModel implementation (Part 14)."""
    import app.api.routes.orchestrations as routes_module

    source = routes_module.__file__
    assert source is not None
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    for forbidden in ("NemotronManagerModel", "ClaudeCodeAdapter", "CodexAdapter", "GeminiAdapter"):
        assert forbidden not in text
