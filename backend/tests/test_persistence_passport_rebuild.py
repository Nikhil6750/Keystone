"""Proves persist -> read -> rebuild is semantically identical to rebuilding
directly from the original in-memory `LearningEvent`s, across every bucket
dimension Stage 5A's pure aggregation supports."""

import random
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.contracts.enums import AgentCapability, AgentExecutionStatus, RuntimeKind
from app.contracts.errors import FailureCategory
from app.contracts.verification import VerificationStatus
from app.engine.learning.events import LearningEvent
from app.engine.learning.passport import rebuild_passport
from app.persistence.execution_repository import ExecutionHistoryRepository
from app.persistence.service import LearningPersistenceService

_UPDATED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _event(
    event_id: str,
    *,
    agent_type: str = "claude_code",
    task_type: str | None = "coding",
    repository_id: str | None = "acme/api",
    capabilities: tuple[AgentCapability, ...] = (AgentCapability.CODE_GENERATION,),
    execution_status: AgentExecutionStatus = AgentExecutionStatus.SUCCEEDED,
    failure_category: FailureCategory | None = None,
    verification_status: VerificationStatus | None = VerificationStatus.PASSED,
    duration_ms: float | None = 100.0,
    cost_usd: float | None = 0.02,
    created_at: datetime | None = None,
) -> LearningEvent:
    return LearningEvent(
        event_id=event_id,
        workflow_id="wf-rebuild",
        agent_type=agent_type,
        execution_status=execution_status,
        created_at=created_at or _UPDATED_AT,
        runtime_kind=RuntimeKind.AGENT_CLI,
        task_type=task_type,
        repository_id=repository_id,
        capabilities=capabilities,
        failure_category=failure_category,
        verification_status=verification_status,
        duration_ms=duration_ms,
        cost_usd=cost_usd,
    )


def _diverse_event_set() -> list[LearningEvent]:
    return [
        _event("pe-1", task_type="coding", repository_id="acme/api", duration_ms=100.0),
        _event(
            "pe-2",
            task_type="testing",
            repository_id="acme/api",
            verification_status=VerificationStatus.FAILED,
            duration_ms=200.0,
        ),
        _event(
            "pe-3",
            task_type="coding",
            repository_id="acme/web",
            capabilities=(AgentCapability.CODE_REVIEW,),
            duration_ms=150.0,
            cost_usd=None,
        ),
        _event(
            "pe-4",
            task_type="testing",
            repository_id="acme/web",
            execution_status=AgentExecutionStatus.FAILED,
            failure_category=FailureCategory.PROVIDER_ERROR,
            verification_status=None,
            duration_ms=50.0,
        ),
        _event(
            "pe-5",
            task_type="coding",
            repository_id="acme/api",
            verification_status=VerificationStatus.INCONCLUSIVE,
            capabilities=(AgentCapability.CODE_GENERATION, AgentCapability.CODE_REVIEW),
            duration_ms=300.0,
        ),
        _event(
            "pe-6",
            task_type=None,
            repository_id=None,
            verification_status=VerificationStatus.REQUIRES_HUMAN_REVIEW,
            duration_ms=75.0,
        ),
    ]


def _persist_all(session: Session, events: list[LearningEvent]) -> None:
    service = LearningPersistenceService()
    for event in events:
        service.record_learning_event(session, event, auto_rebuild_passport=False)
    session.commit()


def test_rebuild_from_persisted_history_matches_direct_rebuild_overall(
    db_session: Session,
) -> None:
    events = _diverse_event_set()
    _persist_all(db_session, events)

    direct = rebuild_passport(events, agent_type="claude_code", updated_at=_UPDATED_AT)

    service = LearningPersistenceService()
    from_db = service.rebuild_agent_passport(db_session, "claude_code", updated_at=_UPDATED_AT)
    db_session.commit()

    assert from_db.overall_metrics == direct.overall_metrics
    assert from_db.overall_verification == direct.overall_verification
    assert from_db.passport.execution_count == direct.passport.execution_count
    assert from_db.passport.success_count == direct.passport.success_count
    assert from_db.passport.failure_count == direct.passport.failure_count
    assert from_db.known_cost_usd_average == direct.known_cost_usd_average
    assert from_db.known_cost_sample_count == direct.known_cost_sample_count


def test_rebuild_from_persisted_history_matches_direct_rebuild_task_type(
    db_session: Session,
) -> None:
    events = _diverse_event_set()
    _persist_all(db_session, events)
    direct = rebuild_passport(events, agent_type="claude_code", updated_at=_UPDATED_AT)

    service = LearningPersistenceService()
    from_db = service.rebuild_agent_passport(db_session, "claude_code", updated_at=_UPDATED_AT)
    db_session.commit()

    assert set(from_db.task_type_buckets) == set(direct.task_type_buckets)
    for key, bucket in direct.task_type_buckets.items():
        assert from_db.task_type_buckets[key] == bucket


def test_rebuild_from_persisted_history_matches_direct_rebuild_repository(
    db_session: Session,
) -> None:
    events = _diverse_event_set()
    _persist_all(db_session, events)
    direct = rebuild_passport(events, agent_type="claude_code", updated_at=_UPDATED_AT)

    service = LearningPersistenceService()
    from_db = service.rebuild_agent_passport(db_session, "claude_code", updated_at=_UPDATED_AT)
    db_session.commit()

    assert set(from_db.repository_buckets) == set(direct.repository_buckets)
    for key, bucket in direct.repository_buckets.items():
        assert from_db.repository_buckets[key] == bucket


def test_rebuild_from_persisted_history_matches_direct_rebuild_capability(
    db_session: Session,
) -> None:
    events = _diverse_event_set()
    _persist_all(db_session, events)
    direct = rebuild_passport(events, agent_type="claude_code", updated_at=_UPDATED_AT)

    service = LearningPersistenceService()
    from_db = service.rebuild_agent_passport(db_session, "claude_code", updated_at=_UPDATED_AT)
    db_session.commit()

    assert set(from_db.capability_buckets) == set(direct.capability_buckets)
    for key, bucket in direct.capability_buckets.items():
        assert from_db.capability_buckets[key] == bucket


def test_rebuild_from_persisted_history_matches_direct_rebuild_repository_task_type(
    db_session: Session,
) -> None:
    events = _diverse_event_set()
    _persist_all(db_session, events)
    direct = rebuild_passport(events, agent_type="claude_code", updated_at=_UPDATED_AT)

    service = LearningPersistenceService()
    from_db = service.rebuild_agent_passport(db_session, "claude_code", updated_at=_UPDATED_AT)
    db_session.commit()

    assert set(from_db.repository_task_type_buckets) == set(direct.repository_task_type_buckets)
    for key, bucket in direct.repository_task_type_buckets.items():
        assert from_db.repository_task_type_buckets[key] == bucket


def test_rebuild_from_persisted_history_is_order_independent(db_session: Session) -> None:
    """Recording events in shuffled order must still rebuild an identical
    passport -- persistence never depends on insertion order."""
    events = _diverse_event_set()
    shuffled = list(events)
    random.Random(3).shuffle(shuffled)

    _persist_all(db_session, shuffled)
    direct = rebuild_passport(events, agent_type="claude_code", updated_at=_UPDATED_AT)

    service = LearningPersistenceService()
    from_db = service.rebuild_agent_passport(db_session, "claude_code", updated_at=_UPDATED_AT)
    db_session.commit()

    assert from_db.overall_metrics == direct.overall_metrics
    assert from_db.overall_verification == direct.overall_verification
    assert from_db.task_type_buckets == direct.task_type_buckets
    assert from_db.repository_buckets == direct.repository_buckets


def test_repeated_rebuild_is_deterministic(db_session: Session) -> None:
    events = _diverse_event_set()
    _persist_all(db_session, events)

    service = LearningPersistenceService()
    first = service.rebuild_agent_passport(db_session, "claude_code", updated_at=_UPDATED_AT)
    db_session.commit()
    for _ in range(5):
        again = service.rebuild_agent_passport(db_session, "claude_code", updated_at=_UPDATED_AT)
        db_session.commit()
        assert again == first


def test_no_aggregation_formula_duplicated_in_persistence_layer(db_session: Session) -> None:
    """Sanity check: the persistence layer's rebuild path and a raw,
    directly-imported Stage 5A call produce bit-identical results for a
    hand-picked edge case (zero verification samples, missing cost)."""
    events = [
        _event(
            "edge-1",
            verification_status=None,
            cost_usd=None,
            duration_ms=None,
        )
    ]
    repo = ExecutionHistoryRepository()
    for event in events:
        repo.record_event(db_session, event)
    db_session.commit()

    direct = rebuild_passport(events, agent_type="claude_code", updated_at=_UPDATED_AT)
    service = LearningPersistenceService()
    from_db = service.rebuild_agent_passport(db_session, "claude_code", updated_at=_UPDATED_AT)
    db_session.commit()

    assert from_db.overall_verification.verification_sample_count == 0
    assert from_db.overall_verification.verified_success_rate is None
    assert from_db.known_cost_usd_average is None
    assert from_db == direct
