"""Tests for retry behavior integrated into `WorkflowEngine`."""

import time

import pytest
from sqlalchemy.orm import Session

from app.engine.executor import StepExecutionError
from app.engine.registry import ExecutorRegistry
from app.engine.workflow_engine import WorkflowEngine
from app.models.enums import AttemptStatus, StepStatus, WorkflowStatus
from app.models.workflow import Workflow
from app.resilience.circuit_breaker import CircuitBreakerRegistry
from app.resilience.retry import RetryPolicy
from app.schemas.workflow import WorkflowCreate, WorkflowStepCreate
from app.services import workflow_service
from tests.support.executors import (
    FailingExecutor,
    RecordingExecutor,
    RetryableFailingExecutor,
    SequencedExecutor,
)
from tests.support.fakes import FakeSleeper


def _create_workflow(
    db_session: Session, steps: list[WorkflowStepCreate], **overrides: object
) -> Workflow:
    data: dict[str, object] = {"name": "demo", "input_payload": {}, "steps": steps}
    data.update(overrides)
    return workflow_service.create_workflow(db_session, WorkflowCreate(**data))  # type: ignore[arg-type]


def test_max_attempts_one_performs_one_total_attempt(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor = RetryableFailingExecutor()
    executor_registry.register("mock", executor)
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="s", position=0, agent_type="mock", max_attempts=1)]
    )

    result = workflow_engine.execute_workflow(workflow.id)

    assert len(executor.calls) == 1
    assert result.steps[0].attempt_count == 1
    assert result.status == WorkflowStatus.FAILED


def test_max_attempts_three_performs_at_most_three_total_attempts(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor = RetryableFailingExecutor()
    executor_registry.register("mock", executor)
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="s", position=0, agent_type="mock", max_attempts=3)]
    )

    result = workflow_engine.execute_workflow(workflow.id)

    assert len(executor.calls) == 3
    assert result.steps[0].attempt_count == 3
    assert result.status == WorkflowStatus.FAILED


def test_retryable_errors_are_retried(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor = SequencedExecutor(
        outcomes=[
            StepExecutionError("transient", error_type="TRANSIENT", retryable=True),
            {"ok": True},
        ]
    )
    executor_registry.register("mock", executor)
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="s", position=0, agent_type="mock", max_attempts=3)]
    )

    result = workflow_engine.execute_workflow(workflow.id)

    assert len(executor.calls) == 2
    assert result.status == WorkflowStatus.SUCCEEDED


def test_non_retryable_errors_are_not_retried(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor = FailingExecutor()  # retryable=False by default
    executor_registry.register("mock", executor)
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="s", position=0, agent_type="mock", max_attempts=3)]
    )

    result = workflow_engine.execute_workflow(workflow.id)

    assert len(executor.calls) == 1
    assert result.status == WorkflowStatus.FAILED


def test_injected_sleeper_receives_expected_delays(
    db_session: Session,
    executor_registry: ExecutorRegistry,
    fake_sleeper: FakeSleeper,
) -> None:
    executor = RetryableFailingExecutor()
    executor_registry.register("mock", executor)
    retry_policy = RetryPolicy(base_delay_seconds=1.0, max_delay_seconds=100.0, jitter_ratio=0.0)
    engine = WorkflowEngine(
        db_session,
        executor_registry,
        circuit_breakers=CircuitBreakerRegistry(
            failure_threshold=100, recovery_timeout_seconds=30.0
        ),
        retry_policy=retry_policy,
        sleeper=fake_sleeper,
    )
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="s", position=0, agent_type="mock", max_attempts=3)]
    )

    engine.execute_workflow(workflow.id)

    assert fake_sleeper.calls == [1.0, 2.0]


def test_no_real_sleeping_occurs(
    db_session: Session,
    workflow_engine: WorkflowEngine,
    executor_registry: ExecutorRegistry,
    fake_sleeper: FakeSleeper,
) -> None:
    executor = RetryableFailingExecutor()
    executor_registry.register("mock", executor)
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="s", position=0, agent_type="mock", max_attempts=3)]
    )

    start = time.monotonic()
    workflow_engine.execute_workflow(workflow.id)
    elapsed = time.monotonic() - start

    assert elapsed < 1.0  # real sleeping would take seconds given the retry policy delays
    assert len(fake_sleeper.calls) == 2


def test_successful_retry_persists_all_failed_and_successful_attempts(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor = SequencedExecutor(
        outcomes=[
            StepExecutionError("transient", error_type="TRANSIENT", retryable=True),
            {"ok": True},
        ]
    )
    executor_registry.register("mock", executor)
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="s", position=0, agent_type="mock", max_attempts=3)]
    )

    result = workflow_engine.execute_workflow(workflow.id)

    attempts = result.steps[0].attempts
    assert len(attempts) == 2
    assert attempts[0].status == AttemptStatus.FAILED
    assert attempts[1].status == AttemptStatus.SUCCEEDED


def test_attempt_numbers_are_sequential(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor = SequencedExecutor(
        outcomes=[
            StepExecutionError("t1", error_type="T", retryable=True),
            StepExecutionError("t2", error_type="T", retryable=True),
            {"ok": True},
        ]
    )
    executor_registry.register("mock", executor)
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="s", position=0, agent_type="mock", max_attempts=3)]
    )

    result = workflow_engine.execute_workflow(workflow.id)

    attempt_numbers = [attempt.attempt_number for attempt in result.steps[0].attempts]
    assert attempt_numbers == [1, 2, 3]


def test_attempt_count_never_exceeds_max_attempts(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor = RetryableFailingExecutor()
    executor_registry.register("mock", executor)
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="s", position=0, agent_type="mock", max_attempts=2)]
    )

    result = workflow_engine.execute_workflow(workflow.id)

    assert result.steps[0].attempt_count == 2
    assert result.steps[0].attempt_count <= 2


def test_step_transitions_through_retrying(
    db_session: Session,
    workflow_engine: WorkflowEngine,
    executor_registry: ExecutorRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    step_statuses: list[StepStatus] = []
    original_transition_step = workflow_service.transition_step

    def _tracking_transition_step(db: Session, step_id: str, target: StepStatus) -> object:
        step_statuses.append(target)
        return original_transition_step(db, step_id, target)

    monkeypatch.setattr(workflow_service, "transition_step", _tracking_transition_step)

    executor = SequencedExecutor(
        outcomes=[
            StepExecutionError("transient", error_type="TRANSIENT", retryable=True),
            {"ok": True},
        ]
    )
    executor_registry.register("mock", executor)
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="s", position=0, agent_type="mock", max_attempts=3)]
    )

    workflow_engine.execute_workflow(workflow.id)

    assert StepStatus.RETRYING in step_statuses


def test_final_exhaustion_fails_step_and_workflow(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor = RetryableFailingExecutor()
    executor_registry.register("mock", executor)
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="s", position=0, agent_type="mock", max_attempts=2)]
    )

    result = workflow_engine.execute_workflow(workflow.id)

    assert result.steps[0].status == StepStatus.FAILED
    assert result.status == WorkflowStatus.FAILED


def test_later_steps_remain_pending_after_retry_exhaustion(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("bad", RetryableFailingExecutor())
    executor_registry.register("good", RecordingExecutor(output={"ok": True}))
    workflow = _create_workflow(
        db_session,
        [
            WorkflowStepCreate(name="first", position=0, agent_type="bad", max_attempts=1),
            WorkflowStepCreate(name="second", position=1, agent_type="good"),
        ],
    )

    result = workflow_engine.execute_workflow(workflow.id)

    assert result.steps[1].status == StepStatus.PENDING


def test_earlier_successful_outputs_remain_persisted_after_retry_exhaustion(
    db_session: Session, workflow_engine: WorkflowEngine, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("good", RecordingExecutor(output={"ok": True}))
    executor_registry.register("bad", RetryableFailingExecutor())
    workflow = _create_workflow(
        db_session,
        [
            WorkflowStepCreate(name="first", position=0, agent_type="good"),
            WorkflowStepCreate(name="second", position=1, agent_type="bad", max_attempts=1),
        ],
    )

    result = workflow_engine.execute_workflow(workflow.id)

    assert result.steps[0].status == StepStatus.SUCCEEDED
    assert result.steps[0].output_payload == {"ok": True}
