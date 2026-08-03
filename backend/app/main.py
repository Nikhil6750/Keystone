"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.adapters.factory import register_agents
from app.api.errors import register_exception_handlers
from app.api.routes.agents import router as agents_router
from app.api.routes.audit import router as audit_router
from app.api.routes.health import router as health_router
from app.api.routes.resilience import router as resilience_router
from app.api.routes.workflows import router as workflows_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.database.init_db import initialize_database
from app.engine.compensation_registry import CompensationRegistry
from app.engine.demo_compensation import DEMO_COMPENSATION_HANDLER_NAME, DemoCompensationHandler
from app.engine.registry import ExecutorRegistry
from app.resilience.circuit_breaker import CircuitBreakerRegistry
from app.resilience.retry import RetryPolicy

configure_logging()
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Log application startup/shutdown, initialize the database, and create the
    per-application executor registry, circuit-breaker registry, retry policy,
    and compensation-handler registry, then register only enabled-and-available
    agent adapters (and the demo compensation handler, only when demo mode is
    enabled).

    Never launches a real agent process and never probes provider
    authentication at startup; an unavailable or misconfigured optional agent
    is logged and skipped, not fatal to startup. Never requires a
    compensation handler to be configured for the application to start.
    """
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


@app.get("/")
def read_root() -> dict[str, str]:
    """Root endpoint confirming the service is running."""
    return {"service": settings.app_name, "version": settings.app_version}
