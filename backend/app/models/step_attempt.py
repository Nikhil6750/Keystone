"""StepAttempt ORM model: one execution attempt of a workflow step."""

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
from app.models.enums import AttemptStatus

if TYPE_CHECKING:
    from app.models.workflow_step import WorkflowStep


class StepAttempt(Base):
    """One execution attempt of a workflow step; retained after success or failure."""

    __tablename__ = "step_attempts"
    __table_args__ = (
        UniqueConstraint("step_id", "attempt_number", name="uq_step_attempt_number"),
        CheckConstraint("attempt_number >= 1", name="ck_step_attempt_number_min"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    step_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_steps.id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[AttemptStatus] = mapped_column(
        SqlEnum(
            AttemptStatus,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            native_enum=False,
            length=20,
        ),
        nullable=False,
        default=AttemptStatus.RUNNING,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    output_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    step: Mapped["WorkflowStep"] = relationship(back_populates="attempts")
