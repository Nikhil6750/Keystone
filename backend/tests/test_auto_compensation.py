"""Tests for optional automatic compensation after workflow execution failure."""

import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.engine.compensation_registry import CompensationRegistry
from app.engine.registry import ExecutorRegistry
from app.engine.workflow_engine import WorkflowEngine
from app.models.enums import StepStatus, WorkflowStatus
from app.resilience.circuit_breaker import CircuitBreakerOpenError, CircuitBreakerRegistry
from app.resilience.retry import RetryPolicy
from app.schemas.workflow import WorkflowCreate, WorkflowStepCreate
from app.services import workflow_service
from tests.support.compensation_handlers import (
    FailingCompensationHandler,
    RecordingCompensationHandler,
)
from tests.support.executors import (
    FailingExecutor,
    RecordingExecutor,
    RetryableFailingExecutor,
)
from tests.support.fakes import FakeSleeper


def _create_workflow(db_session: Session, steps: list[WorkflowStepCreate]):
    return workflow_service.create_workflow(
        db_session, WorkflowCreate(name="demo", input_payload={}, steps=steps)
    )


def _engine(
    db_session: Session,
    executor_registry: ExecutorRegistry,
    compensation_registry: CompensationRegistry,
    *,
    auto_compensate: bool,
) -> WorkflowEngine:
    return WorkflowEngine(
        db_session,
        executor_registry,
        circuit_breakers=CircuitBreakerRegistry(
            failure_threshold=100, recovery_timeout_seconds=300.0
        ),
        retry_policy=RetryPolicy(base_delay_seconds=0.01, max_delay_seconds=0.05),
        sleeper=FakeSleeper(),
        compensation_registry=compensation_registry,
        auto_compensate_on_failure=auto_compensate,
    )


def test_automatic_compensation_is_disabled_by_default() -> None:
    settings = Settings()
    assert settings.auto_compensate_on_failure is False


def test_disabled_behavior_preserves_existing_phase3_failure_behavior(
    db_session: Session,
    executor_registry: ExecutorRegistry,
    compensation_registry: CompensationRegistry,
) -> None:
    executor_registry.register("mock", FailingExecutor())
    engine = _engine(db_session, executor_registry, compensation_registry, auto_compensate=False)
    workflow = _create_workflow(
        db_session,
        [
            WorkflowStepCreate(
                name="s0", position=0, agent_type="mock", compensation_handler="demo.undo"
            )
        ],
    )

    result = engine.execute_workflow(workflow.id)

    assert result.status == WorkflowStatus.FAILED
    assert result.steps[0].status == StepStatus.FAILED  # never transitioned toward compensation


def test_enabled_behavior_compensates_eligible_prior_successful_steps(
    db_session: Session,
    executor_registry: ExecutorRegistry,
    compensation_registry: CompensationRegistry,
) -> None:
    executor_registry.register("good", RecordingExecutor(output={"ok": True}))
    executor_registry.register("bad", FailingExecutor())
    compensation_registry.register(
        "demo.undo", RecordingCompensationHandler(output={"undone": True})
    )
    engine = _engine(db_session, executor_registry, compensation_registry, auto_compensate=True)
    workflow = _create_workflow(
        db_session,
        [
            WorkflowStepCreate(
                name="good", position=0, agent_type="good", compensation_handler="demo.undo"
            ),
            WorkflowStepCreate(name="bad", position=1, agent_type="bad"),
        ],
    )

    result = engine.execute_workflow(workflow.id)

    assert result.status == WorkflowStatus.COMPENSATED
    good_step = next(s for s in result.steps if s.name == "good")
    assert good_step.status == StepStatus.COMPENSATED


def test_enabled_behavior_uses_reverse_order(
    db_session: Session,
    executor_registry: ExecutorRegistry,
    compensation_registry: CompensationRegistry,
) -> None:
    executor_registry.register("good", RecordingExecutor(output={"ok": True}))
    executor_registry.register("bad", FailingExecutor())
    handler = RecordingCompensationHandler(output={"undone": True})
    compensation_registry.register("demo.undo", handler)
    engine = _engine(db_session, executor_registry, compensation_registry, auto_compensate=True)
    workflow = _create_workflow(
        db_session,
        [
            WorkflowStepCreate(
                name="s0", position=0, agent_type="good", compensation_handler="demo.undo"
            ),
            WorkflowStepCreate(
                name="s1", position=1, agent_type="good", compensation_handler="demo.undo"
            ),
            WorkflowStepCreate(name="s2", position=2, agent_type="bad"),
        ],
    )

    engine.execute_workflow(workflow.id)

    assert [call.step_position for call in handler.calls] == [1, 0]


def test_enabled_behavior_does_nothing_when_no_eligible_successful_step(
    db_session: Session,
    executor_registry: ExecutorRegistry,
    compensation_registry: CompensationRegistry,
) -> None:
    executor_registry.register("bad", FailingExecutor())
    engine = _engine(db_session, executor_registry, compensation_registry, auto_compensate=True)
    workflow = _create_workflow(
        db_session, [WorkflowStepCreate(name="s0", position=0, agent_type="bad")]
    )

    result = engine.execute_workflow(workflow.id)

    assert result.status == WorkflowStatus.COMPENSATED
    assert result.compensation_summary is not None
    assert result.compensation_summary["compensated_steps"] == []


def test_enabled_behavior_does_not_recurse(
    db_session: Session,
    executor_registry: ExecutorRegistry,
    compensation_registry: CompensationRegistry,
) -> None:
    """A single automatic-compensation pass runs at most once per failed execution."""
    executor_registry.register("good", RecordingExecutor(output={"ok": True}))
    executor_registry.register("bad", FailingExecutor())
    handler = RecordingCompensationHandler(output={"undone": True})
    compensation_registry.register("demo.undo", handler)
    engine = _engine(db_session, executor_registry, compensation_registry, auto_compensate=True)
    workflow = _create_workflow(
        db_session,
        [
            WorkflowStepCreate(
                name="good", position=0, agent_type="good", compensation_handler="demo.undo"
            ),
            WorkflowStepCreate(name="bad", position=1, agent_type="bad"),
        ],
    )

    engine.execute_workflow(workflow.id)

    assert len(handler.calls) == 1


def test_circuit_open_failure_compensates_earlier_eligible_successful_steps_only(
    db_session: Session,
    executor_registry: ExecutorRegistry,
    compensation_registry: CompensationRegistry,
) -> None:
    """A step's circuit only rejects a call outright (`CircuitBreakerOpenError`
    from `breaker.before_call()`, with the executor never invoked) once it is
    already open from a prior failure — a single `retryable` failure with
    `failure_threshold=1` trips the breaker but still fails via the ordinary
    `StepExecutionError` retry-exhaustion path for that same call. So the
    breaker is pre-tripped with a throwaway workflow first, sharing the same
    `circuit_breakers` registry as the real (second) workflow under test."""
    executor_registry.register("good", RecordingExecutor(output={"ok": True}))
    executor_registry.register("bad", RetryableFailingExecutor())
    compensation_registry.register(
        "demo.undo", RecordingCompensationHandler(output={"undone": True})
    )
    engine = WorkflowEngine(
        db_session,
        executor_registry,
        circuit_breakers=CircuitBreakerRegistry(
            failure_threshold=1, recovery_timeout_seconds=300.0
        ),
        retry_policy=RetryPolicy(base_delay_seconds=0.01, max_delay_seconds=0.05),
        sleeper=FakeSleeper(),
        compensation_registry=compensation_registry,
        auto_compensate_on_failure=True,
    )
    throwaway = _create_workflow(
        db_session, [WorkflowStepCreate(name="bad", position=0, agent_type="bad", max_attempts=1)]
    )
    engine.execute_workflow(throwaway.id)

    workflow = _create_workflow(
        db_session,
        [
            WorkflowStepCreate(
                name="good", position=0, agent_type="good", compensation_handler="demo.undo"
            ),
            WorkflowStepCreate(name="bad", position=1, agent_type="bad", max_attempts=1),
        ],
    )

    with pytest.raises(CircuitBreakerOpenError):
        engine.execute_workflow(workflow.id)

    reloaded = workflow_service.get_workflow(db_session, workflow.id)
    assert reloaded is not None
    assert reloaded.status == WorkflowStatus.COMPENSATED
    good_step = next(s for s in reloaded.steps if s.name == "good")
    assert good_step.status == StepStatus.COMPENSATED


def test_retry_exhaustion_can_trigger_compensation_when_enabled(
    db_session: Session,
    executor_registry: ExecutorRegistry,
    compensation_registry: CompensationRegistry,
) -> None:
    executor_registry.register("good", RecordingExecutor(output={"ok": True}))
    executor_registry.register("bad", RetryableFailingExecutor())
    compensation_registry.register(
        "demo.undo", RecordingCompensationHandler(output={"undone": True})
    )
    engine = _engine(db_session, executor_registry, compensation_registry, auto_compensate=True)
    workflow = _create_workflow(
        db_session,
        [
            WorkflowStepCreate(
                name="good", position=0, agent_type="good", compensation_handler="demo.undo"
            ),
            WorkflowStepCreate(name="bad", position=1, agent_type="bad", max_attempts=2),
        ],
    )

    result = engine.execute_workflow(workflow.id)

    assert result.status == WorkflowStatus.COMPENSATED


def test_compensation_failure_after_automatic_trigger_is_persisted(
    db_session: Session,
    executor_registry: ExecutorRegistry,
    compensation_registry: CompensationRegistry,
) -> None:
    executor_registry.register("good", RecordingExecutor(output={"ok": True}))
    executor_registry.register("bad", FailingExecutor())
    compensation_registry.register("demo.undo", FailingCompensationHandler())
    engine = _engine(db_session, executor_registry, compensation_registry, auto_compensate=True)
    workflow = _create_workflow(
        db_session,
        [
            WorkflowStepCreate(
                name="good", position=0, agent_type="good", compensation_handler="demo.undo"
            ),
            WorkflowStepCreate(name="bad", position=1, agent_type="bad"),
        ],
    )

    # Automatic compensation is best-effort: its own failure is logged and
    # swallowed, never masking the original execution failure's return value.
    result = engine.execute_workflow(workflow.id)

    assert result.status == WorkflowStatus.FAILED
    reloaded = workflow_service.get_workflow(db_session, workflow.id)
    assert reloaded is not None
    assert reloaded.compensation_summary is not None
    assert reloaded.compensation_summary["failed_compensation_step"] is not None


def test_no_handler_executes_twice(
    db_session: Session,
    executor_registry: ExecutorRegistry,
    compensation_registry: CompensationRegistry,
) -> None:
    executor_registry.register("good", RecordingExecutor(output={"ok": True}))
    executor_registry.register("bad", FailingExecutor())
    handler = RecordingCompensationHandler(output={"undone": True})
    compensation_registry.register("demo.undo", handler)
    engine = _engine(db_session, executor_registry, compensation_registry, auto_compensate=True)
    workflow = _create_workflow(
        db_session,
        [
            WorkflowStepCreate(
                name="good", position=0, agent_type="good", compensation_handler="demo.undo"
            ),
            WorkflowStepCreate(name="bad", position=1, agent_type="bad"),
        ],
    )

    engine.execute_workflow(workflow.id)

    assert len(handler.calls) == 1
