"""CompensationAttempt ORM model: one compensation-handler invocation for a step.

Distinct from `StepAttempt`: a `StepAttempt` records one *execution* of a
step's agent; a `CompensationAttempt` records one *reversal* of an already
successful step, run by a compensation handler instead of an agent. The two
have different meanings and are never reused for each other.
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
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.enums import CompensationAttemptStatus

if TYPE_CHECKING:
    from app.models.workflow_step import WorkflowStep


class CompensationAttempt(Base):
    """One compensation-handler invocation for a workflow step."""

    __tablename__ = "compensation_attempts"
    __table_args__ = (
        UniqueConstraint("step_id", "attempt_number", name="uq_compensation_attempt_number"),
        CheckConstraint("attempt_number >= 1", name="ck_compensation_attempt_number_min"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    step_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_steps.id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    handler_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[CompensationAttemptStatus] = mapped_column(
        SqlEnum(
            CompensationAttemptStatus,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            native_enum=False,
            length=20,
        ),
        nullable=False,
        default=CompensationAttemptStatus.RUNNING,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    output_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    step: Mapped["WorkflowStep"] = relationship(back_populates="compensation_attempts")
