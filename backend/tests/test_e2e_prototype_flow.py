"""Prototype-integration E2E: proves the real, wired production pipeline

    HTTP request
    -> POST /api/v1/orchestrations
    -> Planner/Router (real)
    -> WorkflowEngine (real)
    -> Stage 9D Software Quality Factory (real, wired)
    -> Stage 9E Engineering Intelligence Graph (real, wired)
    -> persisted workflow + quality run + intelligence graph
    -> GET /api/v1/orchestrations/{id}
    -> GET /api/v1/quality/runs/{run_id}
    -> GET /api/v1/intelligence/agents/{agent_type}/reliability

end to end, through the real FastAPI app and a real (in-memory) database --
never by directly instantiating quality/intelligence classes in isolation.
Uses a deterministic in-process test executor (no external CLI, no network,
no paid provider), matching the demo/test-runtime intent described for the
prototype's local E2E path.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_orchestration_execution_coordinator, get_orchestration_execution_store
from app.contracts.adapter import AgentDescriptor
from app.contracts.enums import AgentCapability, AgentStatus, RuntimeKind
from app.contracts.quality import (
    QualityGateSpec,
    QualityGateStatus,
    QualityGateType,
    QualityProfile,
)
from app.database.base import Base
from app.database.session import enable_sqlite_foreign_keys
from app.engine.intelligence.builder import EngineeringIntelligenceGraphBuilder
from app.engine.intelligence.graph_repository import SqlAlchemyIntelligenceGraphRepository
from app.engine.intelligence.query_service import EngineeringIntelligenceQueryService
from app.engine.orchestration.events import OrchestrationEventSequence, OrchestrationEventSink
from app.engine.orchestration.execution import (
    InMemoryOrchestrationExecutionStore,
    OrchestrationExecutionCoordinator,
    ServiceFactory,
)
from app.engine.orchestration.models import OrchestrationRequest
from app.engine.orchestration.runtime import StaticCandidateProvider
from app.engine.orchestration.service import EndToEndOrchestrationService
from app.engine.quality.coordinator import QualityFactoryCoordinator
from app.engine.quality.executors import MockQualityGateExecutor
from app.engine.quality.registry import QualityGateExecutorRegistry
from app.engine.quality.repository import SqlAlchemyQualityRepository
from app.engine.registry import ExecutorRegistry
from app.engine.routing.availability import CandidateAgent
from app.main import app
from app.models import audit_event as _audit_event  # noqa: F401
from app.models import compensation_attempt as _compensation_attempt  # noqa: F401
from app.models import intelligence as _intelligence  # noqa: F401
from app.models import quality as _quality  # noqa: F401
from app.models import step_attempt as _step_attempt  # noqa: F401
from app.models import workflow as _workflow  # noqa: F401
from app.models import workflow_step as _workflow_step  # noqa: F401
from app.resilience.circuit_breaker import CircuitBreakerRegistry, CircuitState
from app.resilience.retry import RetryPolicy
from tests.support.executors import RecordingExecutor
from tests.support.orchestration_api_fakes import EchoingFakeManagerModel

_TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled"}

_AGENT_TYPE = "e2e-prototype-agent"

_RICH_OUTPUT = {
    "content": "implemented and tested",
    "exit_code": 0,
    "output": "5 passed in 0.05s",
    "tests_total": 5,
    "tests_passed": 5,
    "tests_failed": 0,
    "tests_skipped": 0,
    "metadata": {"execution_mode": "e2e-test", "exit_code": 0},
}


@pytest.fixture
def e2e_db_engine() -> Engine:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(bind=engine)
    return engine


def _build_full_pipeline_factory(
    *,
    db_engine: Engine,
    gate_status: QualityGateStatus,
) -> tuple[ServiceFactory, SqlAlchemyQualityRepository, SqlAlchemyIntelligenceGraphRepository]:
    """A real `ServiceFactory` wiring the same production components
    `app.main.py` wires at startup (quality coordinator + intelligence
    builder included), pointed at an isolated in-memory database instead of
    a subprocess-driven CLI adapter."""
    session_factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    registry = ExecutorRegistry()
    registry.register(_AGENT_TYPE, RecordingExecutor(output=dict(_RICH_OUTPUT)))
    manager = EchoingFakeManagerModel(agent_type=_AGENT_TYPE)

    descriptor = AgentDescriptor(
        agent_type=_AGENT_TYPE,
        display_name="E2E prototype test agent",
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

    quality_repository = SqlAlchemyQualityRepository(session_factory=session_factory)
    quality_repository.save_profile(
        QualityProfile(
            profile_id="e2e-default-profile",
            name="E2E Default Profile",
            gates=(
                QualityGateSpec(
                    gate_id="e2e-tests", gate_type=QualityGateType.TEST, name="Tests", required=True
                ),
            ),
            is_default=True,
        )
    )
    quality_registry = QualityGateExecutorRegistry()
    quality_registry.register_executor(
        QualityGateType.TEST, MockQualityGateExecutor(default_status=gate_status)
    )
    quality_coordinator = QualityFactoryCoordinator(
        repository=quality_repository, registry=quality_registry
    )

    graph_repo = SqlAlchemyIntelligenceGraphRepository(session_factory=session_factory)
    intelligence_builder = EngineeringIntelligenceGraphBuilder(
        graph_repo, session_factory, quality_repository=quality_repository
    )

    def factory(
        request: OrchestrationRequest,
        event_sink: OrchestrationEventSink,
        event_sequence: OrchestrationEventSequence,
    ) -> tuple[EndToEndOrchestrationService, Callable[[], None]]:
        db = session_factory()
        service = EndToEndOrchestrationService(
            db=db,
            registry=registry,
            candidate_provider=candidate_provider,
            manager_model=manager,
            circuit_breakers=CircuitBreakerRegistry(
                failure_threshold=3, recovery_timeout_seconds=30.0
            ),
            retry_policy=RetryPolicy(
                base_delay_seconds=0.01, max_delay_seconds=0.05, jitter_ratio=0.0
            ),
            event_sink=event_sink,
            event_sequence=event_sequence,
            quality_coordinator=quality_coordinator,
            intelligence_builder=intelligence_builder,
        )
        return service, db.close

    return factory, quality_repository, graph_repo


@asynccontextmanager
async def _full_pipeline_client(
    db_engine: Engine, *, gate_status: QualityGateStatus
) -> AsyncIterator[AsyncClient]:
    factory, quality_repository, graph_repo = _build_full_pipeline_factory(
        db_engine=db_engine, gate_status=gate_status
    )
    store = InMemoryOrchestrationExecutionStore()
    coordinator = OrchestrationExecutionCoordinator(store=store, service_factory=factory)

    # `GET /api/v1/quality/...` and `.../intelligence/...` read
    # `request.app.state.quality_repository`/`.intelligence_query_service`
    # directly (not via `Depends`, see those routers' own dependency
    # providers) -- so proving those APIs see this same isolated database
    # requires overriding `app.state` itself, not just
    # `app.dependency_overrides`.
    had_quality_repo = hasattr(app.state, "quality_repository")
    previous_quality_repo = getattr(app.state, "quality_repository", None)
    had_query_service = hasattr(app.state, "intelligence_query_service")
    previous_query_service = getattr(app.state, "intelligence_query_service", None)

    app.state.quality_repository = quality_repository
    app.state.intelligence_query_service = EngineeringIntelligenceQueryService(graph_repo)
    app.dependency_overrides[get_orchestration_execution_store] = lambda: store
    app.dependency_overrides[get_orchestration_execution_coordinator] = lambda: coordinator
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_orchestration_execution_store, None)
        app.dependency_overrides.pop(get_orchestration_execution_coordinator, None)
        if had_quality_repo:
            app.state.quality_repository = previous_quality_repo
        else:
            del app.state.quality_repository
        if had_query_service:
            app.state.intelligence_query_service = previous_query_service
        else:
            del app.state.intelligence_query_service


async def _poll_until_terminal(client: AsyncClient, execution_id: str) -> dict[str, Any]:
    async def _poll() -> dict[str, Any]:
        while True:
            resp = await client.get(f"/api/v1/orchestrations/{execution_id}")
            assert resp.status_code == 200
            body: dict[str, Any] = resp.json()
            if body["job_status"] in _TERMINAL_JOB_STATUSES:
                return body
            await asyncio.sleep(0.02)

    return await asyncio.wait_for(_poll(), timeout=10.0)


@pytest.mark.asyncio
async def test_full_pipeline_happy_path_wires_quality_and_intelligence(
    e2e_db_engine: Engine, tmp_path: Path
) -> None:
    """Proves the real production wiring end to end: workflow creation,
    execution, a passing Stage 9D quality verdict, and a Stage 9E
    intelligence graph -- all reachable through the public HTTP API, not
    constructed by hand."""
    async with _full_pipeline_client(
        e2e_db_engine, gate_status=QualityGateStatus.PASSED
    ) as client:
        create_resp = await client.post(
            "/api/v1/orchestrations",
            json={
                "goal": "Implement a REST endpoint with tests",
                "available_agent_types": [_AGENT_TYPE],
                "workspace_root": str(tmp_path),
            },
        )
        assert create_resp.status_code == 202
        execution_id = create_resp.json()["execution_id"]

        final = await _poll_until_terminal(client, execution_id)

        assert final["orchestration_outcome"] == "verified_success"
        assert final["workflow_id"] is not None
        assert final["final_workflow_state"] == "succeeded"
        assert final["quality_run_id"] is not None
        assert final["quality_verdict_status"] == "ACCEPTED"

        # Independently retrieve the quality evidence through its own API,
        # not from anything the orchestration response itself computed.
        quality_resp = await client.get(f"/api/v1/quality/runs/{final['quality_run_id']}")
        assert quality_resp.status_code == 200
        quality_body = quality_resp.json()
        assert quality_body["passed"] is True
        assert quality_body["status"] == "ACCEPTED"

        gates_resp = await client.get(f"/api/v1/quality/runs/{final['quality_run_id']}/gates")
        assert gates_resp.status_code == 200
        gates = gates_resp.json()
        assert len(gates) >= 1
        assert all(g["status"] == "PASSED" for g in gates)

        # Independently retrieve intelligence reliability for the agent
        # that just executed -- proves Stage 9E projection actually ran as
        # part of this real HTTP-triggered orchestration.
        reliability_resp = await client.get(
            f"/api/v1/intelligence/agents/{_AGENT_TYPE}/reliability"
        )
        assert reliability_resp.status_code == 200
        reliability = reliability_resp.json()
        assert reliability["observed_executions"] >= 1
        assert reliability["successful_executions"] >= 1
        assert reliability["quality_verified_successes"] >= 1


@pytest.mark.asyncio
async def test_full_pipeline_quality_rejection_is_not_reported_as_success(
    e2e_db_engine: Engine, tmp_path: Path
) -> None:
    """Deliberate failure path: the agent execution itself succeeds, but
    the required Stage 9D quality gate fails -- the orchestration must
    report failure, never verified success, and the rejection must be
    visible through both the orchestration and quality APIs."""
    async with _full_pipeline_client(
        e2e_db_engine, gate_status=QualityGateStatus.FAILED
    ) as client:
        create_resp = await client.post(
            "/api/v1/orchestrations",
            json={
                "goal": "Implement a REST endpoint with tests",
                "available_agent_types": [_AGENT_TYPE],
                "workspace_root": str(tmp_path),
            },
        )
        assert create_resp.status_code == 202
        execution_id = create_resp.json()["execution_id"]

        final = await _poll_until_terminal(client, execution_id)

        assert final["orchestration_outcome"] != "verified_success"
        assert final["quality_verdict_status"] in ("REJECTED", "ERROR")

        quality_resp = await client.get(f"/api/v1/quality/runs/{final['quality_run_id']}")
        assert quality_resp.status_code == 200
        assert quality_resp.json()["passed"] is False


@pytest.mark.asyncio
async def test_unknown_agent_type_is_a_safe_terminal_failure_not_a_5xx(
    e2e_db_engine: Engine, tmp_path: Path
) -> None:
    """Deliberate failure path: an `available_agent_types` entry the
    backend has no registered executor for must resolve to a clean,
    observable terminal failure -- never a 500 and never a false success."""
    async with _full_pipeline_client(
        e2e_db_engine, gate_status=QualityGateStatus.PASSED
    ) as client:
        create_resp = await client.post(
            "/api/v1/orchestrations",
            json={
                "goal": "Implement a REST endpoint with tests",
                "available_agent_types": ["totally-unregistered-agent"],
                "workspace_root": str(tmp_path),
            },
        )
        assert create_resp.status_code == 202
        execution_id = create_resp.json()["execution_id"]

        final = await _poll_until_terminal(client, execution_id)

        assert final["orchestration_outcome"] == "no_eligible_route"
        assert final["orchestration_outcome"] != "verified_success"
