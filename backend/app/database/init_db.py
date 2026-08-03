"""Explicit database schema initialization."""

from app import models  # noqa: F401  (import registers ORM models on Base.metadata)
from app.database.base import Base
from app.database.session import engine


def initialize_database() -> None:
    """Create all defined tables if they do not already exist. Never drops or recreates tables."""
    Base.metadata.create_all(bind=engine)
