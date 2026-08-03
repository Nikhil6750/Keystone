"""Shared pytest fixtures."""

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.database.base import Base
from app.database.session import enable_sqlite_foreign_keys
from app.main import app

# Import models so they register on Base.metadata before create_all() runs below.
from app.models import step_attempt as _step_attempt  # noqa: F401
from app.models import workflow as _workflow  # noqa: F401
from app.models import workflow_step as _workflow_step  # noqa: F401


@pytest.fixture
async def client() -> AsyncClient:
    """An async HTTP client wired directly to the FastAPI ASGI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


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
