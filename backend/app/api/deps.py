"""FastAPI dependency providers for the API layer."""

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.adapters.connection import AgentConnectionCache
from app.core.config import Settings, get_settings
from app.database.session import get_db
from app.engine.compensation import CompensationService
from app.engine.compensation_registry import CompensationRegistry
from app.engine.connections.repository import (
    AgentConnectionRepository,
    ConnectedAgentRepository,
)
from app.engine.orchestration.execution import (
    OrchestrationExecutionCoordinator,
    OrchestrationExecutionStore,
)
from app.engine.registry import ExecutorRegistry
from app.engine.workflow_engine import WorkflowEngine
from app.resilience.circuit_breaker import CircuitBreakerRegistry
from app.resilience.retry import RetryPolicy


def get_executor_registry(request: Request) -> ExecutorRegistry:
    """Return the application's executor registry, created during lifespan startup.

    Reads from `request.app.state` rather than a module-level singleton, so
    each application instance (and each test's overridden app state) owns its
    own registry.
    """
    registry: ExecutorRegistry = request.app.state.executor_registry
    return registry


def get_circuit_breaker_registry(request: Request) -> CircuitBreakerRegistry:
    """Return the application's circuit-breaker registry, created during lifespan startup."""
    registry: CircuitBreakerRegistry = request.app.state.circuit_breaker_registry
    return registry


def get_retry_policy(request: Request) -> RetryPolicy:
    """Return the application's retry policy, created during lifespan startup."""
    policy: RetryPolicy = request.app.state.retry_policy
    return policy


def get_compensation_registry(request: Request) -> CompensationRegistry:
    """Return the application's compensation-handler registry, created during lifespan startup."""
    registry: CompensationRegistry = request.app.state.compensation_registry
    return registry


def get_workflow_engine(
    db: Session = Depends(get_db),  # noqa: B008
    registry: ExecutorRegistry = Depends(get_executor_registry),  # noqa: B008
    circuit_breakers: CircuitBreakerRegistry = Depends(get_circuit_breaker_registry),  # noqa: B008
    retry_policy: RetryPolicy = Depends(get_retry_policy),  # noqa: B008
    compensation_registry: CompensationRegistry = Depends(get_compensation_registry),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> WorkflowEngine:
    """Build a `WorkflowEngine` wired to this request's DB session and the app's registries."""
    return WorkflowEngine(
        db,
        registry,
        circuit_breakers=circuit_breakers,
        retry_policy=retry_policy,
        compensation_registry=compensation_registry,
        auto_compensate_on_failure=settings.auto_compensate_on_failure,
    )


def get_compensation_service(
    db: Session = Depends(get_db),  # noqa: B008
    registry: CompensationRegistry = Depends(get_compensation_registry),  # noqa: B008
) -> CompensationService:
    """Build a `CompensationService` wired to this request's DB session and handler registry."""
    return CompensationService(db, registry)


def get_agent_connection_cache(request: Request) -> AgentConnectionCache:
    """Return the application's agent-connection cache, created during lifespan startup."""
    cache: AgentConnectionCache = request.app.state.agent_connection_cache
    return cache


def get_orchestration_execution_store(request: Request) -> OrchestrationExecutionStore:
    """Return the application's orchestration execution store, created
    during lifespan startup. Overridden in tests exactly like every other
    `app.state`-backed dependency here -- see `tests/conftest.py`."""
    store: OrchestrationExecutionStore = request.app.state.orchestration_execution_store
    return store


def get_orchestration_execution_coordinator(request: Request) -> OrchestrationExecutionCoordinator:
    """Return the application's orchestration execution coordinator,
    created once during lifespan startup (never per-request: it owns the
    only strong reference keeping background execution tasks alive -- see
    `app.engine.orchestration.execution`)."""
    coordinator: OrchestrationExecutionCoordinator = (
        request.app.state.orchestration_execution_coordinator
    )
    return coordinator


def get_agent_connection_repository(request: Request) -> AgentConnectionRepository:
    """Return the application's AgentConnectionRepository, created during lifespan startup."""
    repo: AgentConnectionRepository | None = getattr(
        request.app.state, "agent_connection_repository", None
    )
    if repo is None:
        raise RuntimeError("AgentConnectionRepository is not initialized on app.state")
    return repo


def get_connected_agent_repository(request: Request) -> ConnectedAgentRepository:
    """Return the application's ConnectedAgentRepository, created during lifespan startup."""
    repo: ConnectedAgentRepository | None = getattr(
        request.app.state, "connected_agent_repository", None
    )
    if repo is None:
        raise RuntimeError("ConnectedAgentRepository is not initialized on app.state")
    return repo
