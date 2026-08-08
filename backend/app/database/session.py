"""Centralized SQLAlchemy engine and session management."""

from collections.abc import Iterator
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def _create_engine() -> Engine:
    settings = get_settings()
    url = settings.database_url
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    connect_args: dict[str, Any] = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(url, connect_args=connect_args)


def _sqlite_foreign_keys_listener(dbapi_connection: Any, _connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def enable_sqlite_foreign_keys(target_engine: Engine) -> None:
    """Register SQLite foreign-key enforcement on every new connection for this engine."""
    if target_engine.dialect.name == "sqlite":
        event.listen(target_engine, "connect", _sqlite_foreign_keys_listener)


engine = _create_engine()
enable_sqlite_foreign_keys(engine)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a database session that is always closed after use."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
