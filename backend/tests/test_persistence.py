"""Comprehensive Unit and Integration Tests for Stage 5 Persistence Layer."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.contracts.enums import AgentCapability, AgentExecutionStatus, RuntimeKind
from app.contracts.errors import FailureCategory
from app.contracts.verification import VerificationStatus
from app.engine.learning.events import LearningEvent
from app.engine.learning.passport import rebuild_passport
from app.persistence.errors import LearningEventConflictError
from app.persistence.execution_repository import ExecutionHistoryRepository
from app.persistence.passport_repository import AgentPassportRepository
from app.persistence.service import LearningPersistenceService, build_event_id


def _create_sample_event(
    event_id: str = "evt-101",
    workflow_id: str = "wf-001",
    agent_type: str = "claude_code",
    execution_status: AgentExecutionStatus = AgentExecutionStatus.SUCCEEDED,
    attempt_number: int = 1,
    step_id: str | None = "step-1",
    task_type: str | None = "coding",
    repository_id: str | None = "acme/api",
    verification_status: VerificationStatus | None = VerificationStatus.PASSED,
    duration_ms: float | None = 250.0,
    failure_category: FailureCategory | None = None,
    capabilities: tuple[AgentCapability, ...] = (AgentCapability.CODE_GENERATION,),
    created_at: datetime | None = None,
) -> LearningEvent:
    now = created_at or datetime.now(UTC)
    return LearningEvent(
        event_id=event_id,
        workflow_id=workflow_id,
        agent_type=agent_type,
        execution_status=execution_status,
        attempt_number=attempt_number,
        step_id=step_id,
        runtime_kind=RuntimeKind.AGENT_CLI,
        task_type=task_type,
        repository_id=repository_id,
        capabilities=capabilities,
        failure_category=failure_category,
        duration_ms=duration_ms,
        verification_status=verification_status,
        cost_usd=0.05,
        created_at=now,
    )


# -----------------------------------------------------------------------------
# Domain 1: Execution History Persistence Tests
# -----------------------------------------------------------------------------


def test_insert_and_retrieve_execution_event(db_session: Session) -> None:
    repo = ExecutionHistoryRepository()
    event = _create_sample_event(event_id="evt-1")

    repo.record_event(db_session, event)
    db_session.commit()

    retrieved = repo.get_event_by_id(db_session, "evt-1")
    assert retrieved is not None
    assert retrieved.event_id == "evt-1"
    assert retrieved.workflow_id == "wf-001"
    assert retrieved.agent_type == "claude_code"
    assert retrieved.execution_status == "succeeded"
    assert retrieved.attempt_number == 1
    assert retrieved.duration_ms == 250.0
    assert retrieved.real_cost == 0.05
    assert retrieved.cancelled is False

    domain_event = repo.record_to_domain(retrieved)
    assert domain_event.event_id == event.event_id
    assert domain_event.execution_status == AgentExecutionStatus.SUCCEEDED


def test_preserve_attempt_numbers_and_retry_count(db_session: Session) -> None:
    repo = ExecutionHistoryRepository()
    event_attempt_1 = _create_sample_event(event_id="evt-att-1", attempt_number=1)
    event_attempt_3 = _create_sample_event(event_id="evt-att-3", attempt_number=3)

    repo.record_event(db_session, event_attempt_1)
    repo.record_event(db_session, event_attempt_3)
    db_session.commit()

    rec1 = repo.get_event_by_id(db_session, "evt-att-1")
    rec3 = repo.get_event_by_id(db_session, "evt-att-3")

    assert rec1 is not None and rec3 is not None
    assert rec1.attempt_number == 1
    assert rec1.retry_count == 0
    assert rec3.attempt_number == 3
    assert rec3.retry_count == 2


def test_store_verification_status_and_failure_category(db_session: Session) -> None:
    repo = ExecutionHistoryRepository()
    event_failed = _create_sample_event(
        event_id="evt-fail-1",
        execution_status=AgentExecutionStatus.FAILED,
        failure_category=FailureCategory.PROVIDER_ERROR,
        verification_status=VerificationStatus.FAILED,
    )

    repo.record_event(db_session, event_failed)
    db_session.commit()

    rec = repo.get_event_by_id(db_session, "evt-fail-1")
    assert rec is not None
    assert rec.execution_status == "failed"
    assert rec.failure_category == "provider_error"
    assert rec.verification_status == "failed"


def test_store_cancellation_info(db_session: Session) -> None:
    repo = ExecutionHistoryRepository()
    event_cancelled = _create_sample_event(
        event_id="evt-cancel-1",
        execution_status=AgentExecutionStatus.CANCELLED,
        failure_category=FailureCategory.CANCELLED,
        verification_status=None,
    )

    repo.record_event(db_session, event_cancelled)
    db_session.commit()

    rec = repo.get_event_by_id(db_session, "evt-cancel-1")
    assert rec is not None
    assert rec.execution_status == "cancelled"
    assert rec.failure_category == "cancelled"
    assert rec.cancelled is True


def test_query_execution_history_filters(db_session: Session) -> None:
    repo = ExecutionHistoryRepository()
    now = datetime.now(UTC)

    e1 = _create_sample_event(
        event_id="evt-q1",
        workflow_id="wf-A",
        agent_type="claude_code",
        task_type="coding",
        repository_id="repo-1",
        created_at=now - timedelta(minutes=10),
    )
    e2 = _create_sample_event(
        event_id="evt-q2",
        workflow_id="wf-A",
        agent_type="codex",
        task_type="testing",
        repository_id="repo-1",
        created_at=now - timedelta(minutes=5),
    )
    e3 = _create_sample_event(
        event_id="evt-q3",
        workflow_id="wf-B",
        agent_type="claude_code",
        task_type="coding",
        repository_id="repo-2",
        created_at=now,
    )

    for e in (e1, e2, e3):
        repo.record_event(db_session, e)
    db_session.commit()

    # Query by agent
    claude_events = repo.query_by_agent(db_session, "claude_code")
    assert len(claude_events) == 2

    # Query by task_type
    coding_events = repo.query_by_task_type(db_session, "coding")
    assert len(coding_events) == 2

    # Query by repository
    repo1_events = repo.query_by_repository(db_session, "repo-1")
    assert len(repo1_events) == 2

    # Query by workflow
    wfA_events = repo.query_by_workflow(db_session, "wf-A")
    assert len(wfA_events) == 2

    # Query by time range
    time_events = repo.query_by_time_range(
        db_session,
        start_time=now - timedelta(minutes=7),
        end_time=now + timedelta(minutes=1),
    )
    assert len(time_events) == 2
    assert {r.event_id for r in time_events} == {"evt-q2", "evt-q3"}


def test_identical_duplicate_replay_is_idempotent(db_session: Session) -> None:
    """A byte-identical replay of the same event_id is a safe no-op --
    raw history is never rewritten, but a harmless re-recording never
    raises either."""
    repo = ExecutionHistoryRepository()
    now = datetime.now(UTC)
    e1 = _create_sample_event(event_id="evt-dup", duration_ms=100.0, created_at=now)
    repo.record_event(db_session, e1)
    db_session.commit()

    e1_replay = _create_sample_event(event_id="evt-dup", duration_ms=100.0, created_at=now)
    rec = repo.record_event(db_session, e1_replay)
    db_session.commit()

    assert rec.duration_ms == 100.0
    stored = repo.get_event_by_id(db_session, "evt-dup")
    assert stored is not None
    assert stored.duration_ms == 100.0


def test_identical_duplicate_replay_ignores_created_at_drift(db_session: Session) -> None:
    """created_at is an operational timestamp, not an observed fact --
    two recordings of the same event with different created_at values
    must still be treated as an identical, safe replay."""
    repo = ExecutionHistoryRepository()
    e1 = _create_sample_event(event_id="evt-ts", created_at=datetime(2026, 1, 1, tzinfo=UTC))
    repo.record_event(db_session, e1)
    db_session.commit()

    e1_replay = _create_sample_event(event_id="evt-ts", created_at=datetime(2026, 6, 6, tzinfo=UTC))
    repo.record_event(db_session, e1_replay)  # must not raise
    db_session.commit()


def test_conflicting_replay_different_verification_status_raises(db_session: Session) -> None:
    repo = ExecutionHistoryRepository()
    e1 = _create_sample_event(
        event_id="evt-conflict-1", verification_status=VerificationStatus.PASSED
    )
    repo.record_event(db_session, e1)
    db_session.commit()

    e1_conflict = _create_sample_event(
        event_id="evt-conflict-1", verification_status=VerificationStatus.FAILED
    )
    with pytest.raises(LearningEventConflictError) as exc_info:
        repo.record_event(db_session, e1_conflict)
    assert "verification_status" in exc_info.value.conflicting_fields


def test_conflicting_replay_different_execution_status_raises(db_session: Session) -> None:
    repo = ExecutionHistoryRepository()
    e1 = _create_sample_event(
        event_id="evt-conflict-2", execution_status=AgentExecutionStatus.SUCCEEDED
    )
    repo.record_event(db_session, e1)
    db_session.commit()

    e1_conflict = _create_sample_event(
        event_id="evt-conflict-2",
        execution_status=AgentExecutionStatus.FAILED,
        failure_category=FailureCategory.PROVIDER_ERROR,
        verification_status=None,
    )
    with pytest.raises(LearningEventConflictError) as exc_info:
        repo.record_event(db_session, e1_conflict)
    assert "execution_status" in exc_info.value.conflicting_fields


def test_conflicting_replay_different_cost_raises(db_session: Session) -> None:
    repo = ExecutionHistoryRepository()
    e1 = _create_sample_event(event_id="evt-conflict-3")
    repo.record_event(db_session, e1)
    db_session.commit()

    e1_conflict = LearningEvent(
        event_id="evt-conflict-3",
        workflow_id="wf-001",
        agent_type="claude_code",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        created_at=e1.created_at,
        verification_status=VerificationStatus.PASSED,
        cost_usd=0.99,  # different from the original 0.05
    )
    with pytest.raises(LearningEventConflictError) as exc_info:
        repo.record_event(db_session, e1_conflict)
    assert "real_cost" in exc_info.value.conflicting_fields


def test_conflicting_replay_different_duration_raises(db_session: Session) -> None:
    repo = ExecutionHistoryRepository()
    e1 = _create_sample_event(event_id="evt-conflict-4", duration_ms=100.0)
    repo.record_event(db_session, e1)
    db_session.commit()

    e1_conflict = _create_sample_event(event_id="evt-conflict-4", duration_ms=999.0)
    with pytest.raises(LearningEventConflictError) as exc_info:
        repo.record_event(db_session, e1_conflict)
    assert "duration_ms" in exc_info.value.conflicting_fields


def test_conflicting_replay_passed_then_failed(db_session: Session) -> None:
    """The exact scenario called out explicitly: an event first recorded
    as verified PASSED, later replayed claiming FAILED, must raise -- never
    silently flip historical verification evidence."""
    repo = ExecutionHistoryRepository()
    e1 = _create_sample_event(event_id="evt-flip", verification_status=VerificationStatus.PASSED)
    repo.record_event(db_session, e1)
    db_session.commit()

    e1_flipped = _create_sample_event(
        event_id="evt-flip", verification_status=VerificationStatus.FAILED
    )
    with pytest.raises(LearningEventConflictError):
        repo.record_event(db_session, e1_flipped)

    # The original, correct historical record must remain untouched.
    stored = repo.get_event_by_id(db_session, "evt-flip")
    assert stored is not None
    assert stored.verification_status == "passed"


# -----------------------------------------------------------------------------
# Domain 1b: Event Identity Tests
# -----------------------------------------------------------------------------


def test_event_identity_same_attempt_replay_is_stable() -> None:
    assert build_event_id("wf-1", "step-1", 1) == build_event_id("wf-1", "step-1", 1)


def test_event_identity_retry_attempt_differs() -> None:
    assert build_event_id("wf-1", "step-1", 1) != build_event_id("wf-1", "step-1", 2)


def test_event_identity_different_workflow_differs() -> None:
    assert build_event_id("wf-1", "step-1", 1) != build_event_id("wf-2", "step-1", 1)


def test_event_identity_different_step_differs() -> None:
    assert build_event_id("wf-1", "step-1", 1) != build_event_id("wf-1", "step-2", 1)


def test_event_identity_matches_expected_format() -> None:
    assert build_event_id("wf-1", "step-1", 3) == "evt-wf-1-step-1-3"


# -----------------------------------------------------------------------------
# Domain 1c: Execution/Verification Status Coverage Tests
# -----------------------------------------------------------------------------


def test_cancelled_execution_status_round_trips(db_session: Session) -> None:
    repo = ExecutionHistoryRepository()
    event = _create_sample_event(
        event_id="evt-cancelled",
        execution_status=AgentExecutionStatus.CANCELLED,
        failure_category=FailureCategory.CANCELLED,
        verification_status=None,
    )
    repo.record_event(db_session, event)
    db_session.commit()

    rec = repo.get_event_by_id(db_session, "evt-cancelled")
    assert rec is not None
    domain = repo.record_to_domain(rec)
    assert domain.execution_status is AgentExecutionStatus.CANCELLED
    assert domain.failure_category is FailureCategory.CANCELLED
    assert domain.verification_status is None


def test_timed_out_execution_status_round_trips(db_session: Session) -> None:
    repo = ExecutionHistoryRepository()
    event = _create_sample_event(
        event_id="evt-timeout",
        execution_status=AgentExecutionStatus.TIMED_OUT,
        failure_category=FailureCategory.TIMEOUT,
        verification_status=None,
    )
    repo.record_event(db_session, event)
    db_session.commit()

    rec = repo.get_event_by_id(db_session, "evt-timeout")
    assert rec is not None
    domain = repo.record_to_domain(rec)
    assert domain.execution_status is AgentExecutionStatus.TIMED_OUT
    assert domain.failure_category is FailureCategory.TIMEOUT


def test_execution_succeeded_verification_failed_stored_separately(db_session: Session) -> None:
    """Execution success must never imply verified success -- both facts
    are stored and read back independently."""
    repo = ExecutionHistoryRepository()
    event = _create_sample_event(
        event_id="evt-mismatch",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        verification_status=VerificationStatus.FAILED,
    )
    repo.record_event(db_session, event)
    db_session.commit()

    rec = repo.get_event_by_id(db_session, "evt-mismatch")
    assert rec is not None
    domain = repo.record_to_domain(rec)
    assert domain.execution_status is AgentExecutionStatus.SUCCEEDED
    assert domain.verification_status is VerificationStatus.FAILED


def test_inconclusive_verification_status_round_trips(db_session: Session) -> None:
    repo = ExecutionHistoryRepository()
    event = _create_sample_event(
        event_id="evt-inconclusive", verification_status=VerificationStatus.INCONCLUSIVE
    )
    repo.record_event(db_session, event)
    db_session.commit()

    rec = repo.get_event_by_id(db_session, "evt-inconclusive")
    assert rec is not None
    assert repo.record_to_domain(rec).verification_status is VerificationStatus.INCONCLUSIVE


def test_requires_human_review_verification_status_round_trips(db_session: Session) -> None:
    repo = ExecutionHistoryRepository()
    event = _create_sample_event(
        event_id="evt-human-review",
        verification_status=VerificationStatus.REQUIRES_HUMAN_REVIEW,
    )
    repo.record_event(db_session, event)
    db_session.commit()

    rec = repo.get_event_by_id(db_session, "evt-human-review")
    assert rec is not None
    assert (
        repo.record_to_domain(rec).verification_status is VerificationStatus.REQUIRES_HUMAN_REVIEW
    )


def test_missing_cost_persisted_and_read_back_as_none(db_session: Session) -> None:
    repo = ExecutionHistoryRepository()
    event = LearningEvent(
        event_id="evt-no-cost",
        workflow_id="wf-001",
        agent_type="claude_code",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        created_at=datetime.now(UTC),
        verification_status=VerificationStatus.PASSED,
        cost_usd=None,
    )
    repo.record_event(db_session, event)
    db_session.commit()

    rec = repo.get_event_by_id(db_session, "evt-no-cost")
    assert rec is not None
    assert rec.real_cost is None
    assert repo.record_to_domain(rec).cost_usd is None


# -----------------------------------------------------------------------------
# Domain 2: Agent Passport Aggregates Tests
# -----------------------------------------------------------------------------


def test_create_and_retrieve_agent_passport_aggregates(db_session: Session) -> None:
    passport_repo = AgentPassportRepository()
    now = datetime.now(UTC)

    e1 = _create_sample_event(event_id="p-e1", agent_type="claude_code", created_at=now)
    e2 = _create_sample_event(event_id="p-e2", agent_type="claude_code", created_at=now)
    domain_passport = rebuild_passport([e1, e2], agent_type="claude_code", updated_at=now)

    summary, buckets = passport_repo.create_or_update_passport(db_session, domain_passport)
    db_session.commit()

    assert summary.agent_type == "claude_code"
    assert summary.execution_count == 2
    assert summary.success_count == 2
    assert summary.failure_count == 0

    retrieved_summary = passport_repo.get_passport(db_session, "claude_code")
    assert retrieved_summary is not None
    assert retrieved_summary.execution_count == 2

    retrieved_buckets = passport_repo.get_metric_buckets(db_session, "claude_code")
    assert len(retrieved_buckets) > 0
    overall = [b for b in retrieved_buckets if b.bucket_type == "OVERALL"]
    assert len(overall) == 1
    assert overall[0].sample_count == 2


def test_rebuild_aggregate_metrics_from_raw_events(db_session: Session) -> None:
    service = LearningPersistenceService()
    now = datetime.now(UTC)

    # Insert raw events via service (which automatically updates aggregates)
    e1 = _create_sample_event(
        event_id="rb-1",
        agent_type="claude_code",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        verification_status=VerificationStatus.PASSED,
        created_at=now,
    )
    e2 = _create_sample_event(
        event_id="rb-2",
        agent_type="claude_code",
        execution_status=AgentExecutionStatus.FAILED,
        failure_category=FailureCategory.PROVIDER_ERROR,
        verification_status=VerificationStatus.FAILED,
        created_at=now + timedelta(seconds=1),
    )

    service.record_learning_event(db_session, e1)
    service.record_learning_event(db_session, e2)
    db_session.commit()

    # Verify derived aggregates
    passport_rec = service.passport_repo.get_passport(db_session, "claude_code")
    assert passport_rec is not None
    assert passport_rec.execution_count == 2
    assert passport_rec.success_count == 1
    assert passport_rec.failure_count == 1

    # Now rebuild explicitly from raw history
    rebuilt = service.rebuild_agent_passport(db_session, "claude_code", updated_at=now)
    db_session.commit()

    assert rebuilt.passport.execution_count == 2
    assert rebuilt.passport.success_count == 1
    assert rebuilt.passport.failure_count == 1
    assert rebuilt.overall_verification.verified_success_count == 1
    assert rebuilt.overall_verification.verification_failure_count == 1


def test_agent_and_workflow_isolation(db_session: Session) -> None:
    service = LearningPersistenceService()
    now = datetime.now(UTC)

    # Agent A events
    ea1 = _create_sample_event(
        event_id="iso-a1",
        agent_type="claude_code",
        workflow_id="wf-1",
        created_at=now,
    )
    ea2 = _create_sample_event(
        event_id="iso-a2",
        agent_type="claude_code",
        workflow_id="wf-1",
        created_at=now,
    )

    # Agent B events
    eb1 = _create_sample_event(
        event_id="iso-b1",
        agent_type="codex",
        workflow_id="wf-2",
        created_at=now,
    )

    service.record_learning_event(db_session, ea1)
    service.record_learning_event(db_session, ea2)
    service.record_learning_event(db_session, eb1)
    db_session.commit()

    passport_a = service.passport_repo.get_passport(db_session, "claude_code")
    passport_b = service.passport_repo.get_passport(db_session, "codex")

    assert passport_a is not None and passport_a.execution_count == 2
    assert passport_b is not None and passport_b.execution_count == 1


def test_transaction_rollback_behavior(db_session: Session) -> None:
    repo = ExecutionHistoryRepository()
    e1 = _create_sample_event(event_id="rb-evt-1")

    repo.record_event(db_session, e1)
    db_session.flush()

    # Simulate error and rollback
    db_session.rollback()

    assert repo.get_event_by_id(db_session, "rb-evt-1") is None
