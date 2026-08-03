"""Shared pytest fixtures."""

import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_executor_registry
from app.database.base import Base
from app.database.session import enable_sqlite_foreign_keys, get_db
from app.engine.registry import ExecutorRegistry
from app.engine.workflow_engine import WorkflowEngine
from app.main import app

# Import models so they register on Base.metadata before create_all() runs below.
from app.models import step_attempt as _step_attempt  # noqa: F401
from app.models import workflow as _workflow  # noqa: F401
from app.models import workflow_step as _workflow_step  # noqa: F401


@pytest.fixture
def db_engine(tmp_path: Path) -> Iterator[Engine]:
    """An isolated, file-backed SQLite engine with all tables created."""
    db_path = tmp_path / f"test_{uuid.uuid4().hex}.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        engine.dispose()
        db_path.unlink(missing_ok=True)


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """A database session bound to the isolated test engine, always closed after use."""
    session_factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def executor_registry() -> ExecutorRegistry:
    """A fresh, isolated executor registry for one test."""
    return ExecutorRegistry()


@pytest.fixture
def workflow_engine(db_session: Session, executor_registry: ExecutorRegistry) -> WorkflowEngine:
    """A `WorkflowEngine` wired to the isolated test session and registry."""
    return WorkflowEngine(db_session, executor_registry)


@pytest.fixture
async def client(
    db_engine: Engine, executor_registry: ExecutorRegistry
) -> AsyncIterator[AsyncClient]:
    """An async HTTP client wired to the FastAPI ASGI app.

    Overrides the `get_db` and `get_executor_registry` dependencies so requests
    hit the isolated test database and registry instead of production state or
    a real lifespan (ASGITransport never triggers lifespan events).
    """
    session_factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)

    def _override_get_db() -> Iterator[Session]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_executor_registry] = lambda: executor_registry
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as async_client:
            yield async_client
    finally:
        app.dependency_overrides.clear()
