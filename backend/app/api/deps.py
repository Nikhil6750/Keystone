"""FastAPI dependency providers for the API layer."""

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.engine.registry import ExecutorRegistry
from app.engine.workflow_engine import WorkflowEngine


def get_executor_registry(request: Request) -> ExecutorRegistry:
    """Return the application's executor registry, created during lifespan startup.

    Reads from `request.app.state` rather than a module-level singleton, so
    each application instance (and each test's overridden app state) owns its
    own registry.
    """
    registry: ExecutorRegistry = request.app.state.executor_registry
    return registry


def get_workflow_engine(
    db: Session = Depends(get_db),  # noqa: B008
    registry: ExecutorRegistry = Depends(get_executor_registry),  # noqa: B008
) -> WorkflowEngine:
    """Build a `WorkflowEngine` wired to this request's DB session and the app's registry."""
    return WorkflowEngine(db, registry)
