"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.adapters.connection import AgentConnectionCache
from app.adapters.factory import register_agents
from app.api.errors import register_exception_handlers
from app.api.routes.agent_connections import router as agent_connections_router
from app.api.routes.agents import router as agents_router
from app.api.routes.audit import router as audit_router
from app.api.routes.health import router as health_router
from app.api.routes.orchestrations import router as orchestrations_router
from app.api.routes.resilience import router as resilience_router
from app.api.routes.runtime_connections import router as runtime_connections_router
from app.api.routes.workflows import router as workflows_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.database.init_db import initialize_database
from app.database.session import SessionLocal
from app.engine.compensation_registry import CompensationRegistry
from app.engine.connections import (
    AgentConnectionRepository,
    ConnectedAgentCandidateBridge,
    ConnectedAgentRepository,
    ConnectionRegistryCoordinator,
)
from app.engine.demo_compensation import DEMO_COMPENSATION_HANDLER_NAME, DemoCompensationHandler
from app.engine.manager.protocol import ManagerModel
from app.engine.orchestration.events import OrchestrationEventSequence, OrchestrationEventSink
from app.engine.orchestration.execution import (
    InMemoryOrchestrationExecutionStore,
    OrchestrationExecutionCoordinator,
    ServiceFactory,
)
from app.engine.orchestration.models import OrchestrationRequest
from app.engine.orchestration.runtime import STATIC_AGENT_DESCRIPTORS, RegistryCandidateProvider
from app.engine.orchestration.service import EndToEndOrchestrationService
from app.engine.registry import ExecutorRegistry
from app.resilience.circuit_breaker import CircuitBreakerRegistry
from app.resilience.retry import RetryPolicy

configure_logging()
logger = logging.getLogger(__name__)

settings = get_settings()


def _build_orchestration_service_factory(app: FastAPI) -> ServiceFactory:
    """Returns the `ServiceFactory` the orchestration execution coordinator
    uses to build one fresh `EndToEndOrchestrationService` per execution.
    """

    def factory(
        request: OrchestrationRequest,
        event_sink: OrchestrationEventSink,
        event_sequence: OrchestrationEventSequence,
    ) -> tuple[EndToEndOrchestrationService, Callable[[], None]]:
        db = SessionLocal()
        merged_descriptors = dict(STATIC_AGENT_DESCRIPTORS)
        if hasattr(app.state, "connected_agent_repository") and hasattr(
            app.state, "agent_connection_repository"
        ):
            bridge = ConnectedAgentCandidateBridge(
                app.state.agent_connection_repository, app.state.connected_agent_repository
            )
            merged_descriptors.update(bridge.get_descriptors())

        candidate_provider = RegistryCandidateProvider(
            registry=app.state.executor_registry,
            agent_types=tuple(request.available_agent_types),
            descriptors=merged_descriptors,
            connection_cache=app.state.agent_connection_cache,
            circuit_breakers=app.state.circuit_breaker_registry,
        )
        manager_model: ManagerModel | None = getattr(
            app.state, "orchestration_manager_model", None
        )
        service = EndToEndOrchestrationService(
            db=db,
            registry=app.state.executor_registry,
            candidate_provider=candidate_provider,
            manager_model=manager_model,
            circuit_breakers=app.state.circuit_breaker_registry,
            retry_policy=app.state.retry_policy,
            event_sink=event_sink,
            event_sequence=event_sequence,
        )
        return service, db.close

    return factory


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "%s v%s starting in %s mode", settings.app_name, settings.app_version, settings.environment
    )
    initialize_database()
    app.state.executor_registry = ExecutorRegistry()
    app.state.circuit_breaker_registry = CircuitBreakerRegistry(
        failure_threshold=settings.circuit_breaker_failure_threshold,
        recovery_timeout_seconds=settings.circuit_breaker_recovery_timeout_seconds,
    )
    app.state.retry_policy = RetryPolicy(
        base_delay_seconds=settings.retry_base_delay_seconds,
        max_delay_seconds=settings.retry_max_delay_seconds,
        jitter_ratio=settings.retry_jitter_ratio,
    )
    app.state.compensation_registry = CompensationRegistry()
    if settings.demo_enabled:
        app.state.compensation_registry.register(
            DEMO_COMPENSATION_HANDLER_NAME, DemoCompensationHandler()
        )
        logger.info(
            "compensation_handler_registered handler_name=%s", DEMO_COMPENSATION_HANDLER_NAME
        )
    register_agents(app.state.executor_registry, settings)
    app.state.agent_connection_cache = AgentConnectionCache(
        cache_seconds=settings.agent_connection_cache_seconds
    )
    connection_coordinator = ConnectionRegistryCoordinator()
    app.state.agent_connection_repository = AgentConnectionRepository(
        coordinator=connection_coordinator
    )
    app.state.connected_agent_repository = ConnectedAgentRepository(
        coordinator=connection_coordinator
    )
    app.state.orchestration_manager_model = None
    app.state.orchestration_execution_store = InMemoryOrchestrationExecutionStore()
    app.state.orchestration_execution_coordinator = OrchestrationExecutionCoordinator(
        store=app.state.orchestration_execution_store,
        service_factory=_build_orchestration_service_factory(app),
    )
    yield
    logger.info("%s shutting down", settings.app_name)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(health_router, prefix="/api/v1")
app.include_router(workflows_router, prefix="/api/v1")
app.include_router(agents_router, prefix="/api/v1")
app.include_router(resilience_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/api/v1")
app.include_router(orchestrations_router, prefix="/api/v1")
app.include_router(agent_connections_router, prefix="/api/v1")
app.include_router(runtime_connections_router, prefix="/api/v1")


@app.get("/")
def read_root() -> dict[str, str]:
    """Root endpoint confirming the service is running."""
    return {"service": settings.app_name, "version": settings.app_version}
