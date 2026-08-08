"""Execution History Repository for Stage 5 Raw Event Persistence.

**Raw history is never silently rewritten.** `record_event` treats
`event_id` as an immutable identity: recording a byte-identical replay of
an already-stored event is a safe, idempotent no-op (returns the existing
row untouched), but recording a *conflicting* replay -- the same
`event_id` with a different observed fact (a different verification
outcome, cost, duration, execution status, etc.) -- raises
`LearningEventConflictError` rather than overwriting historical evidence.
`created_at` is deliberately excluded from the conflict comparison: it is
an operational timestamp, not an observed fact about the execution, so
harmless timestamp drift (e.g. reserialization) across two recordings of
the same event never triggers a false conflict.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.enums import AgentCapability, AgentExecutionStatus, RuntimeKind
from app.contracts.errors import FailureCategory
from app.contracts.verification import VerificationStatus
from app.engine.learning.events import LearningEvent
from app.persistence.errors import LearningEventConflictError
from app.persistence.models import LearningEventRecord

# Every field compared to decide "identical replay" vs. "conflicting
# replay" -- deliberately every observable fact on LearningEventRecord
# *except* event_id (the identity being looked up) and created_at (an
# operational timestamp, never an observed fact; see module docstring).
_CONFLICT_COMPARISON_FIELDS = (
    "workflow_id",
    "step_id",
    "attempt_number",
    "agent_type",
    "runtime_kind",
    "task_type",
    "repository_id",
    "capabilities",
    "execution_status",
    "failure_category",
    "verification_status",
    "duration_ms",
    "retry_count",
    "cancelled",
    "real_cost",
)


class ExecutionHistoryRepository:
    """Repository handling persistence and retrieval of raw `LearningEvent` execution records."""

    @staticmethod
    def domain_to_record(event: LearningEvent) -> LearningEventRecord:
        """Convert domain `LearningEvent` dataclass to ORM `LearningEventRecord`."""
        capabilities_list = [c.value for c in event.capabilities] if event.capabilities else None
        v_status = event.verification_status.value if event.verification_status else None
        f_category = event.failure_category.value if event.failure_category else None
        r_kind = event.runtime_kind.value if event.runtime_kind else None

        return LearningEventRecord(
            event_id=event.event_id,
            workflow_id=event.workflow_id,
            step_id=event.step_id,
            attempt_number=event.attempt_number,
            agent_type=event.agent_type,
            runtime_kind=r_kind,
            task_type=event.task_type,
            repository_id=event.repository_id,
            capabilities=capabilities_list,
            execution_status=event.execution_status.value,
            failure_category=f_category,
            verification_status=v_status,
            duration_ms=event.duration_ms,
            retry_count=max(0, event.attempt_number - 1),
            cancelled=(event.execution_status == AgentExecutionStatus.CANCELLED),
            real_cost=event.cost_usd,
            created_at=event.created_at,
        )

    @staticmethod
    def record_to_domain(record: LearningEventRecord) -> LearningEvent:
        """Convert ORM `LearningEventRecord` to domain `LearningEvent` dataclass."""
        caps: tuple[AgentCapability, ...] = ()
        if record.capabilities:
            caps = tuple(AgentCapability(c) for c in record.capabilities if c)

        created_at = record.created_at
        if created_at and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)

        r_kind = RuntimeKind(record.runtime_kind) if record.runtime_kind else None
        f_cat = FailureCategory(record.failure_category) if record.failure_category else None
        v_raw = record.verification_status
        v_stat = VerificationStatus(v_raw) if v_raw else None

        return LearningEvent(
            event_id=record.event_id,
            workflow_id=record.workflow_id,
            agent_type=record.agent_type,
            execution_status=AgentExecutionStatus(record.execution_status),
            created_at=created_at,
            attempt_number=record.attempt_number,
            step_id=record.step_id,
            runtime_kind=r_kind,
            task_type=record.task_type,
            repository_id=record.repository_id,
            capabilities=caps,
            failure_category=f_cat,
            duration_ms=record.duration_ms,
            verification_status=v_stat,
            cost_usd=record.real_cost,
        )

    def record_event(self, session: Session, event: LearningEvent) -> LearningEventRecord:
        """Insert a new raw execution learning event, or -- for an
        already-recorded `event_id` -- either return the existing row
        unchanged (byte-identical replay) or raise
        `LearningEventConflictError` (conflicting replay). Never updates a
        historical row's observed facts in place; see module docstring.
        """
        existing = session.get(LearningEventRecord, event.event_id)
        if existing is not None:
            candidate = self.domain_to_record(event)
            conflicting_fields = tuple(
                attr
                for attr in _CONFLICT_COMPARISON_FIELDS
                if getattr(existing, attr) != getattr(candidate, attr)
            )
            if conflicting_fields:
                raise LearningEventConflictError(event.event_id, conflicting_fields)
            return existing

        record = self.domain_to_record(event)
        session.add(record)
        return record

    def get_event_by_id(self, session: Session, event_id: str) -> LearningEventRecord | None:
        """Retrieve execution event record by primary key ID."""
        return session.get(LearningEventRecord, event_id)

    def list_events(
        self, session: Session, limit: int = 100, offset: int = 0
    ) -> Sequence[LearningEventRecord]:
        """List execution event records ordered by creation timestamp."""
        stmt = (
            select(LearningEventRecord)
            .order_by(LearningEventRecord.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return session.scalars(stmt).all()

    def query_by_agent(
        self, session: Session, agent_type: str, limit: int = 100
    ) -> Sequence[LearningEventRecord]:
        """Query execution events for a given agent type."""
        stmt = (
            select(LearningEventRecord)
            .where(LearningEventRecord.agent_type == agent_type)
            .order_by(LearningEventRecord.created_at.asc())
            .limit(limit)
        )
        return session.scalars(stmt).all()

    def query_by_task_type(
        self, session: Session, task_type: str, limit: int = 100
    ) -> Sequence[LearningEventRecord]:
        """Query execution events filtered by task type."""
        stmt = (
            select(LearningEventRecord)
            .where(LearningEventRecord.task_type == task_type)
            .order_by(LearningEventRecord.created_at.asc())
            .limit(limit)
        )
        return session.scalars(stmt).all()

    def query_by_repository(
        self, session: Session, repository_id: str, limit: int = 100
    ) -> Sequence[LearningEventRecord]:
        """Query execution events filtered by repository ID."""
        stmt = (
            select(LearningEventRecord)
            .where(LearningEventRecord.repository_id == repository_id)
            .order_by(LearningEventRecord.created_at.asc())
            .limit(limit)
        )
        return session.scalars(stmt).all()

    def query_by_workflow(
        self, session: Session, workflow_id: str, limit: int = 100
    ) -> Sequence[LearningEventRecord]:
        """Query execution events for a specific workflow ID."""
        stmt = (
            select(LearningEventRecord)
            .where(LearningEventRecord.workflow_id == workflow_id)
            .order_by(LearningEventRecord.created_at.asc())
            .limit(limit)
        )
        return session.scalars(stmt).all()

    def query_by_time_range(
        self,
        session: Session,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        agent_type: str | None = None,
        limit: int = 100,
    ) -> Sequence[LearningEventRecord]:
        """Query execution events within a creation timestamp window."""
        stmt = select(LearningEventRecord)
        if start_time is not None:
            stmt = stmt.where(LearningEventRecord.created_at >= start_time)
        if end_time is not None:
            stmt = stmt.where(LearningEventRecord.created_at <= end_time)
        if agent_type is not None:
            stmt = stmt.where(LearningEventRecord.agent_type == agent_type)
        stmt = stmt.order_by(LearningEventRecord.created_at.asc()).limit(limit)
        return session.scalars(stmt).all()


__all__ = ["ExecutionHistoryRepository"]
