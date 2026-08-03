"""Workflow ORM model: the top-level unit of orchestration."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, CheckConstraint, DateTime, String, Text
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.enums import WorkflowStatus

if TYPE_CHECKING:
    from app.models.audit_event import AuditEvent
    from app.models.workflow_step import WorkflowStep


class Workflow(Base):
    """A workflow: an ordered set of steps executed toward one goal."""

    __tablename__ = "workflows"
    __table_args__ = (CheckConstraint("length(trim(name)) > 0", name="ck_workflow_name_not_blank"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # native_enum=False keeps storage as VARCHAR+CHECK, portable beyond SQLite.
    status: Mapped[WorkflowStatus] = mapped_column(
        SqlEnum(
            WorkflowStatus,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            native_enum=False,
            length=20,
        ),
        nullable=False,
        default=WorkflowStatus.PENDING,
    )
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    output_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Kept separate from output_payload (rather than nesting {"execution", "compensation"}
    # inside it) so the existing execution output_payload shape is never disturbed.
    compensation_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(nullable=False, default=1)

    steps: Mapped[list["WorkflowStep"]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="WorkflowStep.position",
    )
    audit_events: Mapped[list["AuditEvent"]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="AuditEvent.sequence_number",
    )
