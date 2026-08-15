"""SQLAlchemy ORM models for Stage 9E Engineering Intelligence Graph persistence.

Relational projection of the graph domain (`app.contracts.intelligence`):
nodes and edges are plain rows with a deterministic primary key derived from
the canonical evidence they project, so re-ingesting the same source
evidence is naturally idempotent (insert-if-absent, never update-in-place --
see `app.engine.intelligence.builder`). Common query dimensions
(`workflow_id`, `agent_type`, `task_type`, `skill_id`) are denormalized onto
`IntelligenceNodeRecord`/`FailureAttributionRecord` as plain indexed
columns, mirroring `app.persistence.models.LearningEventRecord`'s own
precedent, rather than requiring JSON-path filtering for every reliability
query.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class IntelligenceNodeRecord(Base):
    """Persisted Engineering Intelligence Graph node -- a projection of one
    canonical, already-persisted entity from another Keystone system."""

    __tablename__ = "intelligence_nodes"
    __table_args__ = (
        CheckConstraint("length(trim(node_id)) > 0", name="ck_intelligence_node_id_not_blank"),
        Index("idx_intelligence_nodes_type_workflow", "node_type", "workflow_id"),
        Index("idx_intelligence_nodes_agent_task", "agent_type", "task_type"),
        Index("idx_intelligence_nodes_skill", "skill_id", "skill_version"),
    )

    node_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    node_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    canonical_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    workflow_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    agent_type: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    task_type: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    skill_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    skill_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True)

    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, default=lambda: datetime.now(UTC)
    )


class IntelligenceEdgeRecord(Base):
    """Persisted directed, typed relationship between two intelligence nodes."""

    __tablename__ = "intelligence_edges"
    __table_args__ = (
        UniqueConstraint(
            "source_node_id",
            "target_node_id",
            "edge_type",
            name="uq_intelligence_edge_canonical_relationship",
        ),
        Index("idx_intelligence_edges_source", "source_node_id", "edge_type"),
        Index("idx_intelligence_edges_target", "target_node_id", "edge_type"),
    )

    edge_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    edge_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_node_id: Mapped[str] = mapped_column(String(200), nullable=False)
    target_node_id: Mapped[str] = mapped_column(String(200), nullable=False)

    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, default=lambda: datetime.now(UTC)
    )


class FailureAttributionRecord(Base):
    """Persisted evidence-based failure attribution for one attempt.

    `attribution_id` is deterministic (derived from the attempt and the
    attribution's cause dimension -- execution vs. quality, see the
    builder), so re-ingestion never duplicates or overwrites a previously
    recorded attribution: a later success on a *different*, later attempt
    never touches an earlier attempt's attribution row.
    """

    __tablename__ = "intelligence_failure_attributions"
    __table_args__ = (
        Index("idx_intelligence_failures_dims", "task_type", "agent_type", "skill_id"),
    )

    attribution_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    attempt_node_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    is_known: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    workflow_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    agent_type: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    task_type: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    skill_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, default=lambda: datetime.now(UTC)
    )


__all__ = [
    "FailureAttributionRecord",
    "IntelligenceEdgeRecord",
    "IntelligenceNodeRecord",
]
