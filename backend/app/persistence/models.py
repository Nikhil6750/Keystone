"""SQLAlchemy 2.x declarative ORM models for Stage 5 Persistence.

Contains:
1. `LearningEventRecord`: Raw execution history events (Source of Truth).
2. `AgentPassportRecord`: Derived per-agent passport aggregate metrics.
3. `AgentPassportBucketRecord`: Derived per-bucket metric tallies
   (task_type, repository, capability, etc.).
"""

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class LearningEventRecord(Base):
    """Raw execution history event ORM model.

    Raw execution events are the source of truth for all learning evidence.
    """

    __tablename__ = "learning_events"

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    step_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    agent_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    runtime_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    task_type: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    repository_id: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    capabilities: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    execution_status: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verification_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancelled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    real_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        default=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        CheckConstraint("attempt_number >= 1", name="ck_learning_events_attempt_number"),
        Index("idx_learning_events_agent_created", "agent_type", "created_at"),
        Index("idx_learning_events_task_agent", "task_type", "agent_type"),
        Index("idx_learning_events_repo_agent", "repository_id", "agent_type"),
    )


class AgentPassportRecord(Base):
    """Derived Agent Passport summary aggregate record."""

    __tablename__ = "agent_passports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_type: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    execution_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancellation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    median_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    p95_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    failure_categories: Mapped[dict[str, int] | None] = mapped_column(JSON, nullable=True)
    low_sample_size: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_succeeded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    known_cost_usd_average: Mapped[float | None] = mapped_column(Float, nullable=True)
    known_cost_sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


class AgentPassportBucketRecord(Base):
    """Derived Agent Passport metric bucket record for specific dimensions."""

    __tablename__ = "agent_passport_buckets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    bucket_type: Mapped[str] = mapped_column(String(32), nullable=False)
    bucket_key: Mapped[str] = mapped_column(String(256), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verified_success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verification_failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verification_inconclusive_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    human_review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verification_sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verified_success_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancel_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    p50_latency: Mapped[float | None] = mapped_column(Float, nullable=True)
    p95_latency: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_sample_size: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        UniqueConstraint(
            "agent_type", "bucket_type", "bucket_key", name="uq_agent_passport_bucket"
        ),
        Index("idx_passport_bucket_query", "agent_type", "bucket_type"),
    )


__all__ = [
    "AgentPassportBucketRecord",
    "AgentPassportRecord",
    "LearningEventRecord",
]
