"""Tests for circuit-breaker behavior integrated into `WorkflowEngine`."""

import pytest
from sqlalchemy.orm import Session

from app.engine.executor import StepExecutionError
from app.engine.registry import ExecutorNotRegisteredError, ExecutorRegistry
from app.engine.workflow_engine import WorkflowEngine
from app.models.enums import StepStatus, WorkflowStatus
from app.models.workflow import Workflow
from app.resilience.circuit_breaker import (
    CircuitBreakerOpenError,
    CircuitBreakerRegistry,
    CircuitState,
)
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


def _create_workflow(db_session: Session, steps: list[WorkflowStepCreate]) -> Workflow:
    return workflow_service.create_workflow(
        db_session, WorkflowCreate(name="demo", input_payload={}, steps=steps)
    )


def _engine(
    db_session: Session,
    executor_registry: ExecutorRegistry,
    *,
    failure_threshold: int = 2,
    recovery_timeout_seconds: float = 300.0,
) -> WorkflowEngine:
    return WorkflowEngine(
        db_session,
        executor_registry,
        circuit_breakers=CircuitBreakerRegistry(
            failure_threshold=failure_threshold, recovery_timeout_seconds=recovery_timeout_seconds
        ),
        retry_policy=RetryPolicy(base_delay_seconds=0.01, max_delay_seconds=0.05),
        sleeper=FakeSleeper(),
    )


def test_retryable_failure_followed_by_success_completes_workflow(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    executor = SequencedExecutor(
        outcomes=[
            StepExecutionError("transient", error_type="T", retryable=True),
            {"ok": True},
        ]
    )
    executor_registry.register("mock", executor)
    engine = _engine(db_session, executor_registry, failure_threshold=5)
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="s", position=0, agent_type="mock", max_attempts=3)]
    )

    result = engine.execute_workflow(workflow.id)

    assert result.status == WorkflowStatus.SUCCEEDED


def test_failed_attempts_remain_in_history(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("mock", RetryableFailingExecutor())
    engine = _engine(db_session, executor_registry, failure_threshold=10)
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="s", position=0, agent_type="mock", max_attempts=3)]
    )

    result = engine.execute_workflow(workflow.id)

    assert len(result.steps[0].attempts) == 3


def test_non_retryable_adapter_failure_stops_immediately(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    executor = FailingExecutor()
    executor_registry.register("mock", executor)
    engine = _engine(db_session, executor_registry, failure_threshold=10)
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="s", position=0, agent_type="mock", max_attempts=5)]
    )

    result = engine.execute_workflow(workflow.id)

    assert len(executor.calls) == 1
    assert result.status == WorkflowStatus.FAILED


def test_retry_exhaustion_fails_the_workflow(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("mock", RetryableFailingExecutor())
    engine = _engine(db_session, executor_registry, failure_threshold=10)
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="s", position=0, agent_type="mock", max_attempts=2)]
    )

    result = engine.execute_workflow(workflow.id)

    assert result.status == WorkflowStatus.FAILED
    assert result.steps[0].status == StepStatus.FAILED


def test_circuit_opening_stops_further_retries(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    executor = RetryableFailingExecutor()
    executor_registry.register("mock", executor)
    # Threshold of 1: the very first failure opens the circuit, so the retry
    # loop's own circuit re-check must prevent a second attempt even though
    # max_attempts allows more.
    engine = _engine(db_session, executor_registry, failure_threshold=1)
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="s", position=0, agent_type="mock", max_attempts=5)]
    )

    result = engine.execute_workflow(workflow.id)

    assert len(executor.calls) == 1
    assert result.status == WorkflowStatus.FAILED
    assert result.steps[0].status == StepStatus.FAILED


def test_later_workflow_using_same_agent_is_rejected_by_open_circuit(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    executor = RetryableFailingExecutor()
    executor_registry.register("mock", executor)
    engine = _engine(db_session, executor_registry, failure_threshold=1)

    first_workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="s", position=0, agent_type="mock", max_attempts=1)]
    )
    # max_attempts=1 exhausts immediately; a retryable-but-exhausted failure is
    # a normal handled failure (returned, not raised) — same as Phase 2.
    first_result = engine.execute_workflow(first_workflow.id)
    assert first_result.status == WorkflowStatus.FAILED

    second_workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="s", position=0, agent_type="mock", max_attempts=1)]
    )

    with pytest.raises(CircuitBreakerOpenError):
        engine.execute_workflow(second_workflow.id)

    reloaded = workflow_service.get_workflow(db_session, second_workflow.id)
    assert reloaded is not None
    assert reloaded.status == WorkflowStatus.FAILED
    assert reloaded.steps[0].attempts[0].error_type == "CIRCUIT_BREAKER_OPEN"


def test_workflow_using_different_agent_is_unaffected_by_open_circuit(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("bad", RetryableFailingExecutor())
    executor_registry.register("good", RecordingExecutor(output={"ok": True}))
    engine = _engine(db_session, executor_registry, failure_threshold=1)

    bad_workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="s", position=0, agent_type="bad", max_attempts=1)]
    )
    bad_result = engine.execute_workflow(bad_workflow.id)
    assert bad_result.status == WorkflowStatus.FAILED

    good_workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="s", position=0, agent_type="good")]
    )

    result = engine.execute_workflow(good_workflow.id)

    assert result.status == WorkflowStatus.SUCCEEDED


def test_open_circuit_rejection_creates_documented_blocked_attempt(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    executor = RetryableFailingExecutor()
    executor_registry.register("mock", executor)
    engine = _engine(db_session, executor_registry, failure_threshold=1)

    first_workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="s", position=0, agent_type="mock", max_attempts=1)]
    )
    # max_attempts=1 exhausts immediately; a retryable-but-exhausted failure is
    # a normal handled failure (returned, not raised) — same as Phase 2.
    first_result = engine.execute_workflow(first_workflow.id)
    assert first_result.status == WorkflowStatus.FAILED

    calls_before = len(executor.calls)
    second_workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="s", position=0, agent_type="mock", max_attempts=1)]
    )
    with pytest.raises(CircuitBreakerOpenError):
        engine.execute_workflow(second_workflow.id)

    reloaded = workflow_service.get_workflow(db_session, second_workflow.id)
    assert reloaded is not None
    assert len(reloaded.steps[0].attempts) == 1
    assert reloaded.steps[0].attempts[0].error_type == "CIRCUIT_BREAKER_OPEN"
    assert len(executor.calls) == calls_before  # no new call: adapter was never launched


def test_open_circuit_rejection_launches_no_subprocess(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    executor = RetryableFailingExecutor()
    executor_registry.register("mock", executor)
    circuit_breakers = CircuitBreakerRegistry(failure_threshold=1, recovery_timeout_seconds=300.0)
    engine = WorkflowEngine(
        db_session,
        executor_registry,
        circuit_breakers=circuit_breakers,
        retry_policy=RetryPolicy(base_delay_seconds=0.01, max_delay_seconds=0.05),
        sleeper=FakeSleeper(),
    )
    first_workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="s", position=0, agent_type="mock", max_attempts=1)]
    )
    # max_attempts=1 exhausts immediately; a retryable-but-exhausted failure is
    # a normal handled failure (returned, not raised) — same as Phase 2.
    first_result = engine.execute_workflow(first_workflow.id)
    assert first_result.status == WorkflowStatus.FAILED

    assert circuit_breakers.get_or_create("mock").snapshot().state is CircuitState.OPEN
    calls_before = len(executor.calls)

    second_workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="s", position=0, agent_type="mock", max_attempts=1)]
    )
    with pytest.raises(CircuitBreakerOpenError):
        engine.execute_workflow(second_workflow.id)

    assert len(executor.calls) == calls_before


def test_missing_executor_behavior_remains_unchanged(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    engine = _engine(db_session, executor_registry)
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="s", position=0, agent_type="unregistered")]
    )

    with pytest.raises(ExecutorNotRegisteredError):
        engine.execute_workflow(workflow.id)

    reloaded = workflow_service.get_workflow(db_session, workflow.id)
    assert reloaded is not None
    assert reloaded.status == WorkflowStatus.FAILED
    assert reloaded.steps[0].attempts[0].error_type == "AGENT_EXECUTOR_NOT_REGISTERED"


def test_zero_step_workflow_behavior_remains_unchanged(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    engine = _engine(db_session, executor_registry)
    workflow = _create_workflow(db_session, [])

    result = engine.execute_workflow(workflow.id)

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output_payload == {"steps": []}


def test_successful_output_aggregation_remains_unchanged(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("mock", RecordingExecutor(output={"answer": 42}))
    engine = _engine(db_session, executor_registry)
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="s", position=0, agent_type="mock")]
    )

    result = engine.execute_workflow(workflow.id)

    assert result.output_payload is not None
    assert result.output_payload["steps"][0]["output"] == {"answer": 42}


def test_phase2_transaction_guarantees_remain_valid(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("good", RecordingExecutor(output={"ok": True}))
    executor_registry.register("bad", RetryableFailingExecutor())
    engine = _engine(db_session, executor_registry, failure_threshold=10)
    workflow = _create_workflow(
        db_session,
        [
            WorkflowStepCreate(name="first", position=0, agent_type="good"),
            WorkflowStepCreate(name="second", position=1, agent_type="bad", max_attempts=1),
        ],
    )

    result = engine.execute_workflow(workflow.id)

    assert result.steps[0].status == StepStatus.SUCCEEDED
    assert result.steps[0].output_payload == {"ok": True}
    assert result.steps[1].status == StepStatus.FAILED


def test_database_session_remains_usable_after_handled_retry_failure(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("mock", RetryableFailingExecutor())
    engine = _engine(db_session, executor_registry, failure_threshold=10)
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="s", position=0, agent_type="mock", max_attempts=2)]
    )

    engine.execute_workflow(workflow.id)

    all_workflows = workflow_service.list_workflows(db_session)
    assert len(all_workflows) == 1
