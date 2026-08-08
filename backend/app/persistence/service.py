"""High-level Stage 5 Persistence Service unifying event storage and derived passport rebuilds.

**Sole `LearningEvent` construction boundary for workflow execution.**
`record_step_attempt_outcome` is the only place `app.engine.workflow_engine`
is meant to touch when turning one completed step attempt into learning
evidence -- it builds the `LearningEvent` (including its deterministic
`event_id`, via `build_event_id`) from plain scalar facts the workflow
engine already has on hand, so the workflow engine itself never imports or
constructs `LearningEvent` directly. This keeps the workflow state-machine
layer and the learning-event shape decoupled: a future change to
`LearningEvent`'s fields only ever touches this method's signature, never
scattered construction sites in the engine.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.enums import AgentCapability, AgentExecutionStatus, RuntimeKind
from app.contracts.errors import FailureCategory
from app.contracts.verification import VerificationStatus
from app.engine.learning.events import LearningEvent
from app.engine.learning.passport import LearningPassport
from app.persistence.execution_repository import ExecutionHistoryRepository
from app.persistence.models import LearningEventRecord
from app.persistence.passport_repository import AgentPassportRepository


def build_event_id(workflow_id: str, step_id: str, attempt_number: int) -> str:
    """The deterministic, collision-safe raw-history identity for one step
    attempt's `LearningEvent`.

    Pure function of stable facts only -- never a timestamp, never a random
    UUID. `workflow_id`/`step_id` are already-unique UUID primary keys
    (`app.models.workflow.Workflow`/`app.models.workflow_step.WorkflowStep`),
    and `attempt_number` is unique per step (enforced by
    `uq_step_attempt_number` on `StepAttempt`) -- so the composite
    `(workflow_id, step_id, attempt_number)` can never collide across two
    genuinely different attempts, and replaying the same attempt always
    reproduces the same id.
    """
    return f"evt-{workflow_id}-{step_id}-{attempt_number}"


class LearningPersistenceService:
    """Service boundary integrating raw execution event persistence with derived
    Agent Passport rebuilds.
    """

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
        """Record raw learning event (Source of Truth) and optionally update derived
        passport aggregates.
        """
        record = self.execution_repo.record_event(session, event)
        session.flush()

        passport: LearningPassport | None = None
        if auto_rebuild_passport:
            passport = self.passport_repo.rebuild_passport_from_history(
                session, agent_type=event.agent_type, updated_at=event.created_at
            )

        return record, passport

    def record_step_attempt_outcome(
        self,
        session: Session,
        *,
        workflow_id: str,
        step_id: str,
        attempt_number: int,
        agent_type: str,
        execution_status: AgentExecutionStatus,
        created_at: datetime,
        verification_status: VerificationStatus | None = None,
        failure_category: FailureCategory | None = None,
        task_type: str | None = None,
        repository_id: str | None = None,
        runtime_kind: RuntimeKind | None = None,
        capabilities: tuple[AgentCapability, ...] = (),
        duration_ms: float | None = None,
        cost_usd: float | None = None,
        auto_rebuild_passport: bool = False,
    ) -> tuple[LearningEventRecord, LearningPassport | None]:
        """Build and record the `LearningEvent` for one completed workflow
        step attempt -- the only `LearningEvent`-construction entry point
        `WorkflowEngine` calls (see module docstring).

        `verification_status` defaults to `None` ("not verified yet"),
        never fabricated to `PASSED`: execution success must never imply
        verified success. `auto_rebuild_passport` defaults to `False` here
        (unlike `record_learning_event`'s general-purpose default) so a
        single step attempt does not trigger a full passport rebuild on
        every workflow-engine call in the hot execution path; callers that
        want an up-to-date passport call `rebuild_agent_passport`
        explicitly, e.g. periodically or on workflow completion.
        """
        event = LearningEvent(
            event_id=build_event_id(workflow_id, step_id, attempt_number),
            workflow_id=workflow_id,
            agent_type=agent_type,
            execution_status=execution_status,
            created_at=created_at,
            attempt_number=attempt_number,
            step_id=step_id,
            runtime_kind=runtime_kind,
            task_type=task_type,
            repository_id=repository_id,
            capabilities=capabilities,
            failure_category=failure_category,
            duration_ms=duration_ms,
            verification_status=verification_status,
            cost_usd=cost_usd,
        )
        return self.record_learning_event(
            session, event, auto_rebuild_passport=auto_rebuild_passport
        )

    def get_learning_event(self, session: Session, event_id: str) -> LearningEvent | None:
        """Retrieve raw learning event domain object by ID."""
        record = self.execution_repo.get_event_by_id(session, event_id)
        if not record:
            return None
        return self.execution_repo.record_to_domain(record)

    def rebuild_agent_passport(
        self, session: Session, agent_type: str, *, updated_at: datetime | None = None
    ) -> LearningPassport:
        """Rebuild `LearningPassport` for an agent strictly from historical raw
        events in database.
        """
        now = updated_at or datetime.now(UTC)
        return self.passport_repo.rebuild_passport_from_history(
            session, agent_type=agent_type, updated_at=now
        )

    def rebuild_all_passports(
        self, session: Session, *, updated_at: datetime | None = None
    ) -> dict[str, LearningPassport]:
        """Rebuild passports for all distinct agents present in execution history."""
        now = updated_at or datetime.now(UTC)
        distinct_agents = session.scalars(
            select(LearningEventRecord.agent_type).distinct()
        ).all()

        passports: dict[str, LearningPassport] = {}
        for agent_type in distinct_agents:
            passports[agent_type] = self.passport_repo.rebuild_passport_from_history(
                session, agent_type=agent_type, updated_at=now
            )

        return passports


__all__ = ["LearningPersistenceService", "build_event_id"]
