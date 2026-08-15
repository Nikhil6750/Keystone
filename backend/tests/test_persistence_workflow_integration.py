"""Integration tests proving `WorkflowEngine` creates `LearningEvent`s only
through `LearningPersistenceService`, with correct attempt/verification/
idempotency semantics."""

import contextlib

from sqlalchemy.orm import Session

from app.contracts.enums import AgentExecutionStatus
from app.contracts.errors import FailureCategory
from app.contracts.verification import VerificationStatus
from app.engine.registry import ExecutorRegistry
from app.engine.workflow_engine import _classify_failed_attempt
from app.models.step_attempt import StepAttempt
from app.models.workflow_step import WorkflowStep
from app.persistence.service import LearningPersistenceService, build_event_id
from app.schemas.workflow import WorkflowCreate, WorkflowStepCreate
from app.services import workflow_service
from tests.support.executors import RecordingExecutor, SequencedExecutor


def _build_engine(db_session: Session, executor_registry, **overrides):
    from app.engine.workflow_engine import WorkflowEngine

    kwargs = {
        "learning_persistence": LearningPersistenceService(),
        "retry_policy": overrides.pop("retry_policy", None),
        "sleeper": overrides.pop("sleeper", None),
    }
    kwargs.update(overrides)
    return WorkflowEngine(db_session, executor_registry, **kwargs)


def _create_workflow(
    db_session: Session,
    *,
    task_type: str | None = "coding",
    repository_id: str | None = "acme/api",
    agent_type: str = "claude_code",
    max_attempts: int = 3,
):
    step_input: dict = {}
    if task_type is not None:
        step_input["task_type"] = task_type
    if repository_id is not None:
        step_input["repository_id"] = repository_id
    data = WorkflowCreate(
        name="test-workflow",
        steps=[
            WorkflowStepCreate(
                name="step-1",
                position=0,
                agent_type=agent_type,
                input_payload=step_input,
                max_attempts=max_attempts,
            )
        ],
    )
    return workflow_service.create_workflow(db_session, data)


# --- workflow execution creates LearningEvent only through the service --------------------


def test_successful_step_records_learning_event_via_service(
    db_session: Session, executor_registry: ExecutorRegistry, fake_sleeper
) -> None:
    executor_registry.register("claude_code", RecordingExecutor(output={"ok": True}))
    workflow = _create_workflow(db_session)
    engine = _build_engine(db_session, executor_registry, sleeper=fake_sleeper)

    engine.execute_workflow(workflow.id)

    step = workflow.steps[0]
    event_id = build_event_id(workflow.id, step.id, 1)
    service = LearningPersistenceService()
    event = service.get_learning_event(db_session, event_id)
    assert event is not None
    assert event.execution_status is AgentExecutionStatus.SUCCEEDED
    assert event.workflow_id == workflow.id
    assert event.step_id == step.id
    assert event.attempt_number == 1
    assert event.agent_type == "claude_code"
    assert event.task_type == "coding"
    assert event.repository_id == "acme/api"


def test_execution_success_does_not_imply_verified_success(
    db_session: Session, executor_registry: ExecutorRegistry, fake_sleeper
) -> None:
    """No verification_resolver configured -> execution succeeds, but
    verification_status must stay None, never fabricated to PASSED."""
    executor_registry.register("claude_code", RecordingExecutor(output={"ok": True}))
    workflow = _create_workflow(db_session)
    engine = _build_engine(db_session, executor_registry, sleeper=fake_sleeper)

    engine.execute_workflow(workflow.id)

    step = workflow.steps[0]
    event = LearningPersistenceService().get_learning_event(
        db_session, build_event_id(workflow.id, step.id, 1)
    )
    assert event is not None
    assert event.execution_status is AgentExecutionStatus.SUCCEEDED
    assert event.verification_status is None


def test_verification_resolver_records_real_verified_outcome(
    db_session: Session, executor_registry: ExecutorRegistry, fake_sleeper
) -> None:
    def resolver(step: WorkflowStep, attempt: StepAttempt) -> VerificationStatus:
        return VerificationStatus.PASSED

    executor_registry.register("claude_code", RecordingExecutor(output={"ok": True}))
    workflow = _create_workflow(db_session)
    engine = _build_engine(
        db_session, executor_registry, sleeper=fake_sleeper, verification_resolver=resolver
    )

    engine.execute_workflow(workflow.id)

    step = workflow.steps[0]
    event = LearningPersistenceService().get_learning_event(
        db_session, build_event_id(workflow.id, step.id, 1)
    )
    assert event is not None
    assert event.verification_status is VerificationStatus.PASSED


def test_verification_resolver_can_report_failed_despite_execution_success(
    db_session: Session, executor_registry: ExecutorRegistry, fake_sleeper
) -> None:
    """Execution SUCCEEDED + verification FAILED must be stored as two
    independent facts, never conflated."""

    def resolver(step: WorkflowStep, attempt: StepAttempt) -> VerificationStatus:
        return VerificationStatus.FAILED

    executor_registry.register("claude_code", RecordingExecutor(output={"ok": True}))
    workflow = _create_workflow(db_session)
    engine = _build_engine(
        db_session, executor_registry, sleeper=fake_sleeper, verification_resolver=resolver
    )

    engine.execute_workflow(workflow.id)

    step = workflow.steps[0]
    event = LearningPersistenceService().get_learning_event(
        db_session, build_event_id(workflow.id, step.id, 1)
    )
    assert event is not None
    assert event.execution_status is AgentExecutionStatus.SUCCEEDED
    assert event.verification_status is VerificationStatus.FAILED


def test_terminal_failure_records_failed_learning_event(
    db_session: Session, executor_registry: ExecutorRegistry, fake_sleeper
) -> None:
    from tests.support.executors import FailingExecutor

    executor_registry.register("claude_code", FailingExecutor())
    workflow = _create_workflow(db_session, max_attempts=1)
    engine = _build_engine(db_session, executor_registry, sleeper=fake_sleeper)

    with contextlib.suppress(Exception):
        engine.execute_workflow(workflow.id)

    step = workflow.steps[0]
    event = LearningPersistenceService().get_learning_event(
        db_session, build_event_id(workflow.id, step.id, 1)
    )
    assert event is not None
    assert event.execution_status is AgentExecutionStatus.FAILED
    assert event.failure_category is not None


def test_retries_generate_distinct_attempt_numbers_and_events(
    db_session: Session, executor_registry: ExecutorRegistry, fake_sleeper
) -> None:
    """A retried-then-succeeded step must produce two distinct
    LearningEvents, one per attempt, with distinct attempt_numbers."""
    # Sequenced outcomes: attempt 1 raises retryable, attempt 2 succeeds.
    from app.engine.executor import StepExecutionError

    executor = SequencedExecutor(
        outcomes=[
            StepExecutionError("transient", error_type="SIMULATED_TRANSIENT", retryable=True),
            {"ok": True},
        ]
    )
    executor_registry.register("claude_code", executor)
    workflow = _create_workflow(db_session, max_attempts=3)
    engine = _build_engine(db_session, executor_registry, sleeper=fake_sleeper)

    engine.execute_workflow(workflow.id)

    step = workflow.steps[0]
    service = LearningPersistenceService()
    event_1 = service.get_learning_event(db_session, build_event_id(workflow.id, step.id, 1))
    event_2 = service.get_learning_event(db_session, build_event_id(workflow.id, step.id, 2))

    assert event_1 is not None
    assert event_2 is not None
    assert event_1.event_id != event_2.event_id
    assert event_1.attempt_number == 1
    assert event_2.attempt_number == 2
    assert event_1.execution_status is AgentExecutionStatus.FAILED
    assert event_2.execution_status is AgentExecutionStatus.SUCCEEDED


def test_duplicate_emission_is_safe(
    db_session: Session, executor_registry: ExecutorRegistry, fake_sleeper
) -> None:
    """Recording the same step-attempt outcome twice (simulating a replay)
    must not raise -- it is a byte-identical, idempotent no-op."""
    executor_registry.register("claude_code", RecordingExecutor(output={"ok": True}))
    workflow = _create_workflow(db_session)
    step = workflow.steps[0]
    service = LearningPersistenceService()

    from datetime import UTC, datetime

    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    service.record_step_attempt_outcome(
        db_session,
        workflow_id=workflow.id,
        step_id=step.id,
        attempt_number=1,
        agent_type="claude_code",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        created_at=created_at,
    )
    db_session.commit()

    # Byte-identical replay of the same fact must not raise.
    service.record_step_attempt_outcome(
        db_session,
        workflow_id=workflow.id,
        step_id=step.id,
        attempt_number=1,
        agent_type="claude_code",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        created_at=created_at,
    )
    db_session.commit()


def test_learning_persistence_disabled_by_default(
    db_session: Session, executor_registry: ExecutorRegistry, fake_sleeper
) -> None:
    """A WorkflowEngine built without learning_persistence (the default,
    matching every pre-existing Phase 2/3/4 construction call) must never
    record a LearningEvent."""
    from app.engine.workflow_engine import WorkflowEngine

    executor_registry.register("claude_code", RecordingExecutor(output={"ok": True}))
    workflow = _create_workflow(db_session)
    engine = WorkflowEngine(db_session, executor_registry, sleeper=fake_sleeper)

    engine.execute_workflow(workflow.id)

    step = workflow.steps[0]
    event = LearningPersistenceService().get_learning_event(
        db_session, build_event_id(workflow.id, step.id, 1)
    )
    assert event is None


def test_workflow_engine_never_imports_learning_event_directly() -> None:
    """Structural check: `workflow_engine.py` must build `LearningEvent`s
    only through `LearningPersistenceService.record_step_attempt_outcome`,
    never construct the dataclass itself."""
    import app.engine.workflow_engine as workflow_engine_module

    source_file = workflow_engine_module.__file__
    assert source_file is not None
    with open(source_file, encoding="utf-8") as fh:
        source = fh.read()
    assert "from app.engine.learning.events import LearningEvent" not in source
    assert "LearningEvent(" not in source


# --- _classify_failed_attempt unit coverage (pure, single-event classification) -------------


def test_classify_circuit_breaker_open() -> None:
    status, category = _classify_failed_attempt("CIRCUIT_BREAKER_OPEN")
    assert status is AgentExecutionStatus.FAILED
    assert category is FailureCategory.CIRCUIT_OPEN


def test_classify_timeout() -> None:
    status, category = _classify_failed_attempt("EXECUTOR_TIMEOUT")
    assert status is AgentExecutionStatus.TIMED_OUT
    assert category is FailureCategory.TIMEOUT


def test_classify_cancelled() -> None:
    status, category = _classify_failed_attempt("STEP_CANCELLED")
    assert status is AgentExecutionStatus.CANCELLED
    assert category is FailureCategory.CANCELLED


def test_classify_unrecognized_falls_back_to_unknown() -> None:
    status, category = _classify_failed_attempt("SOME_EXECUTOR_SPECIFIC_ERROR")
    assert status is AgentExecutionStatus.FAILED
    assert category is FailureCategory.UNKNOWN


def test_classify_none_falls_back_to_unknown() -> None:
    status, category = _classify_failed_attempt(None)
    assert status is AgentExecutionStatus.FAILED
    assert category is FailureCategory.UNKNOWN
