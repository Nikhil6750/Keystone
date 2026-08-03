"""WorkflowStep ORM model: one ordered unit of work within a workflow."""

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
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.enums import StepStatus

if TYPE_CHECKING:
    from app.models.compensation_attempt import CompensationAttempt
    from app.models.step_attempt import StepAttempt
    from app.models.workflow import Workflow


class WorkflowStep(Base):
    """A single ordered step within a workflow, executed by one agent."""

    __tablename__ = "workflow_steps"
    __table_args__ = (
        UniqueConstraint("workflow_id", "position", name="uq_workflow_step_position"),
        CheckConstraint("position >= 0", name="ck_workflow_step_position_nonneg"),
        CheckConstraint("max_attempts >= 1", name="ck_workflow_step_max_attempts_min"),
        CheckConstraint("attempt_count >= 0", name="ck_workflow_step_attempt_count_nonneg"),
        CheckConstraint("length(trim(name)) > 0", name="ck_workflow_step_name_not_blank"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[StepStatus] = mapped_column(
        SqlEnum(
            StepStatus,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            native_enum=False,
            length=20,
        ),
        nullable=False,
        default=StepStatus.PENDING,
    )
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    output_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    compensation_handler: Mapped[str | None] = mapped_column(String(255), nullable=True)
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

    workflow: Mapped["Workflow"] = relationship(back_populates="steps")
    attempts: Mapped[list["StepAttempt"]] = relationship(
        back_populates="step",
        cascade="all, delete-orphan",
        order_by="StepAttempt.attempt_number",
    )
    compensation_attempts: Mapped[list["CompensationAttempt"]] = relationship(
        back_populates="step",
        cascade="all, delete-orphan",
        order_by="CompensationAttempt.attempt_number",
    )
