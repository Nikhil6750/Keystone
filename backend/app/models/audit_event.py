"""AuditEvent ORM model: one tamper-evident, hash-linked entry in a workflow's audit chain.

Application services never update or individually delete an `AuditEvent` once
appended (see `app.audit.service`); only a cascading workflow delete removes
its events, which is acceptable for this local, same-day prototype.
"""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.audit.types import ActorType, AuditEventType
from app.database.base import Base

if TYPE_CHECKING:
    from app.models.workflow import Workflow


class AuditEvent(Base):
    """One entry in a workflow's tamper-evident, SHA-256 hash-linked audit chain."""

    __tablename__ = "audit_events"
    __table_args__ = (
        UniqueConstraint("workflow_id", "sequence_number", name="uq_audit_event_sequence"),
        CheckConstraint("sequence_number >= 1", name="ck_audit_event_sequence_min"),
        CheckConstraint("length(previous_hash) = 64", name="ck_audit_event_previous_hash_length"),
        CheckConstraint("length(event_hash) = 64", name="ck_audit_event_event_hash_length"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    step_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    execution_attempt_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    compensation_attempt_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[AuditEventType] = mapped_column(
        SqlEnum(
            AuditEventType,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            native_enum=False,
            length=64,
        ),
        nullable=False,
    )
    actor_type: Mapped[ActorType] = mapped_column(
        SqlEnum(
            ActorType,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            native_enum=False,
            length=32,
        ),
        nullable=False,
    )
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    workflow: Mapped["Workflow"] = relationship(back_populates="audit_events")
