"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_exception_handlers
from app.api.routes.health import router as health_router
from app.api.routes.workflows import router as workflows_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.database.init_db import initialize_database
from app.engine.registry import ExecutorRegistry

configure_logging()
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Log application startup/shutdown, initialize the database, and create the
    per-application executor registry (empty; real adapters are registered in
    Phase 3)."""
    logger.info(
        "%s v%s starting in %s mode", settings.app_name, settings.app_version, settings.environment
    )
    initialize_database()
    app.state.executor_registry = ExecutorRegistry()
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


@app.get("/")
def read_root() -> dict[str, str]:
    """Root endpoint confirming the service is running."""
    return {"service": settings.app_name, "version": settings.app_version}
