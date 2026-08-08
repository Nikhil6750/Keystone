"""High-level Stage 5 Persistence Service unifying event storage and derived passport rebuilds."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.learning.events import LearningEvent
from app.engine.learning.passport import LearningPassport
from app.persistence.execution_repository import ExecutionHistoryRepository
from app.persistence.models import LearningEventRecord
from app.persistence.passport_repository import AgentPassportRepository


class LearningPersistenceService:
    """Service boundary integrating raw execution event persistence with derived Agent Passport rebuilds."""

    def __init__(
        self,
        execution_repo: ExecutionHistoryRepository | None = None,
        passport_repo: AgentPassportRepository | None = None,
    ) -> None:
        self.execution_repo = execution_repo or ExecutionHistoryRepository()
        self.passport_repo = passport_repo or AgentPassportRepository()

    def record_learning_event(
        self,
        session: Session,
        event: LearningEvent,
        *,
        auto_rebuild_passport: bool = True,
    ) -> tuple[LearningEventRecord, LearningPassport | None]:
        """Record raw learning event (Source of Truth) and optionally update derived passport aggregates."""
        record = self.execution_repo.record_event(session, event)
        session.flush()

        passport: LearningPassport | None = None
        if auto_rebuild_passport:
            passport = self.passport_repo.rebuild_passport_from_history(
                session, agent_type=event.agent_type, updated_at=event.created_at
            )

        return record, passport

    def get_learning_event(self, session: Session, event_id: str) -> LearningEvent | None:
        """Retrieve raw learning event domain object by ID."""
        record = self.execution_repo.get_event_by_id(session, event_id)
        if not record:
            return None
        return self.execution_repo.record_to_domain(record)

    def rebuild_agent_passport(
        self, session: Session, agent_type: str, *, updated_at: datetime | None = None
    ) -> LearningPassport:
        """Rebuild `LearningPassport` for an agent strictly from historical raw events in database."""
        now = updated_at or datetime.now(timezone.utc)
        return self.passport_repo.rebuild_passport_from_history(
            session, agent_type=agent_type, updated_at=now
        )

    def rebuild_all_passports(
        self, session: Session, *, updated_at: datetime | None = None
    ) -> dict[str, LearningPassport]:
        """Rebuild passports for all distinct agents present in execution history."""
        now = updated_at or datetime.now(timezone.utc)
        distinct_agents = session.scalars(
            select(LearningEventRecord.agent_type).distinct()
        ).all()

        passports: dict[str, LearningPassport] = {}
        for agent_type in distinct_agents:
            passports[agent_type] = self.passport_repo.rebuild_passport_from_history(
                session, agent_type=agent_type, updated_at=now
            )

        return passports


__all__ = ["LearningPersistenceService"]
