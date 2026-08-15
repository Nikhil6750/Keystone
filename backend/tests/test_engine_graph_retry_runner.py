"""Tests for `RetryingStepRunner`: retry, backoff, and circuit-breaker
awareness layered on top of a plain `StepRunner`, without scheduler changes."""

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.contracts.workflow import WorkflowStepDefinition
from app.engine.workflow.exceptions import StepRunnerError
from app.engine.workflow.retry_runner import RetryingStepRunner
from app.resilience.circuit_breaker import CircuitBreakerRegistry, CircuitState
from app.resilience.retry import RetryPolicy
from tests.support.fakes import FakeClock


@dataclass
class ScriptedInnerRunner:
    """Raises the first `fail_count` calls, then succeeds; or always fails if
    `fail_count` is `None`."""

    fail_count: int | None
    error_type: str = "AGENT_PROCESS_ERROR"
    calls: int = field(default=0, init=False)

    async def run(
        self,
        *,
        workflow_id: str,
        step: WorkflowStepDefinition,
        previous_outputs: dict[str, dict[str, Any]],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        self.calls += 1
        if self.fail_count is None or self.calls <= self.fail_count:
            raise StepRunnerError(f"attempt {self.calls} failed", error_type=self.error_type)
        return {"attempt": self.calls}


def _step(**overrides: Any) -> WorkflowStepDefinition:
    base: dict[str, Any] = {"key": "a", "name": "a", "agent_type": "demo", "max_attempts": 3}
    base.update(overrides)
    return WorkflowStepDefinition.model_validate(base)


def _retrying_runner(inner: ScriptedInnerRunner) -> RetryingStepRunner:
    return RetryingStepRunner(
        inner,
        retry_policy=RetryPolicy(
            base_delay_seconds=0.001, max_delay_seconds=0.005, jitter_ratio=0.0
        ),
        circuit_breakers=CircuitBreakerRegistry(failure_threshold=5, recovery_timeout_seconds=30.0),
    )


async def test_first_attempt_success_never_retries() -> None:
    inner = ScriptedInnerRunner(fail_count=0)
    runner = _retrying_runner(inner)
    output = await runner.run(
        workflow_id="wf-1", step=_step(), previous_outputs={}, timeout_seconds=5.0
    )
    assert output == {"attempt": 1}
    assert inner.calls == 1


async def test_retryable_failure_then_success() -> None:
    inner = ScriptedInnerRunner(fail_count=2, error_type="AGENT_PROCESS_ERROR")
    runner = _retrying_runner(inner)
    output = await runner.run(
        workflow_id="wf-1", step=_step(max_attempts=3), previous_outputs={}, timeout_seconds=5.0
    )
    assert output == {"attempt": 3}
    assert inner.calls == 3


async def test_non_retryable_failure_stops_after_one_attempt() -> None:
    inner = ScriptedInnerRunner(fail_count=None, error_type="AGENT_AUTHENTICATION_ERROR")
    runner = _retrying_runner(inner)
    with pytest.raises(StepRunnerError):
        await runner.run(
            workflow_id="wf-1", step=_step(max_attempts=5), previous_outputs={}, timeout_seconds=5.0
        )
    assert inner.calls == 1


async def test_validation_failure_is_not_retried() -> None:
    inner = ScriptedInnerRunner(fail_count=None, error_type="AGENT_CONFIGURATION_ERROR")
    runner = _retrying_runner(inner)
    with pytest.raises(StepRunnerError):
        await runner.run(
            workflow_id="wf-1", step=_step(max_attempts=5), previous_outputs={}, timeout_seconds=5.0
        )
    assert inner.calls == 1


async def test_retryable_failure_never_exceeds_max_attempts() -> None:
    inner = ScriptedInnerRunner(fail_count=None, error_type="AGENT_PROCESS_ERROR")
    runner = _retrying_runner(inner)
    with pytest.raises(StepRunnerError):
        await runner.run(
            workflow_id="wf-1", step=_step(max_attempts=3), previous_outputs={}, timeout_seconds=5.0
        )
    assert inner.calls == 3


async def test_circuit_breaker_opens_and_stops_calling_the_inner_runner() -> None:
    inner = ScriptedInnerRunner(fail_count=None, error_type="AGENT_PROCESS_ERROR")
    circuit_breakers = CircuitBreakerRegistry(failure_threshold=2, recovery_timeout_seconds=999.0)
    runner = RetryingStepRunner(
        inner,
        retry_policy=RetryPolicy(
            base_delay_seconds=0.001, max_delay_seconds=0.005, jitter_ratio=0.0
        ),
        circuit_breakers=circuit_breakers,
    )
    with pytest.raises(StepRunnerError):
        await runner.run(
            workflow_id="wf-1",
            step=_step(max_attempts=10),
            previous_outputs={},
            timeout_seconds=5.0,
        )
    calls_after_first_run = inner.calls
    assert calls_after_first_run >= 2  # enough failures to trip the breaker

    with pytest.raises(StepRunnerError) as exc_info:
        await runner.run(
            workflow_id="wf-1",
            step=_step(key="b", max_attempts=10),
            previous_outputs={},
            timeout_seconds=5.0,
        )
    assert exc_info.value.error_type == "CIRCUIT_BREAKER_OPEN"
    # The open circuit rejected the call before ever reaching the inner runner again.
    assert inner.calls == calls_after_first_run


@dataclass
class AlwaysFailingRunner:
    """Always raises a retryable `StepRunnerError`, recording every call."""

    error_type: str = "AGENT_PROCESS_ERROR"
    calls: int = field(default=0, init=False)

    async def run(
        self,
        *,
        workflow_id: str,
        step: WorkflowStepDefinition,
        previous_outputs: dict[str, dict[str, Any]],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        self.calls += 1
        raise StepRunnerError(f"attempt {self.calls} failed", error_type=self.error_type)


async def test_cancellation_during_backoff_wait_propagates_cleanly() -> None:
    inner = AlwaysFailingRunner()
    runner = RetryingStepRunner(
        inner,
        retry_policy=RetryPolicy(base_delay_seconds=10.0, max_delay_seconds=10.0, jitter_ratio=0.0),
        circuit_breakers=CircuitBreakerRegistry(
            failure_threshold=100, recovery_timeout_seconds=999.0
        ),
    )
    task = asyncio.ensure_future(
        runner.run(
            workflow_id="wf-1",
            step=_step(max_attempts=5),
            previous_outputs={},
            timeout_seconds=60.0,
        )
    )
    await asyncio.sleep(0.02)  # first attempt has failed; runner is now in the backoff sleep
    assert inner.calls == 1

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # Cancellation mid-backoff must not be swallowed or treated as a retry.
    assert inner.calls == 1


async def test_external_timeout_during_retries_stops_further_attempts() -> None:
    inner = AlwaysFailingRunner()
    runner = RetryingStepRunner(
        inner,
        retry_policy=RetryPolicy(base_delay_seconds=1.0, max_delay_seconds=1.0, jitter_ratio=0.0),
        circuit_breakers=CircuitBreakerRegistry(
            failure_threshold=100, recovery_timeout_seconds=999.0
        ),
    )
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            runner.run(
                workflow_id="wf-1",
                step=_step(max_attempts=5),
                previous_outputs={},
                timeout_seconds=60.0,
            ),
            timeout=0.05,
        )
    calls_at_timeout = inner.calls
    assert calls_at_timeout >= 1

    await asyncio.sleep(0.05)
    # max_attempts=5 was never exhausted — the *external* timeout, not the
    # retry budget, is what stopped this. No further attempts should occur
    # after the timeout cancelled the call. This is the documented
    # interaction: max_attempts is an upper bound on attempts, but an
    # overall per-step timeout imposed by a caller (e.g. GraphScheduler) may
    # terminate execution before that budget is ever fully used.
    assert inner.calls == calls_at_timeout


async def test_half_open_probe_success_closes_circuit() -> None:
    clock = FakeClock()
    circuit_breakers = CircuitBreakerRegistry(
        failure_threshold=1, recovery_timeout_seconds=10.0, clock=clock
    )
    inner = ScriptedInnerRunner(fail_count=1, error_type="AGENT_PROCESS_ERROR")
    runner = RetryingStepRunner(
        inner,
        retry_policy=RetryPolicy(
            base_delay_seconds=0.001, max_delay_seconds=0.005, jitter_ratio=0.0
        ),
        circuit_breakers=circuit_breakers,
    )
    with pytest.raises(StepRunnerError):
        await runner.run(
            workflow_id="wf-1",
            step=_step(key="a", max_attempts=1),
            previous_outputs={},
            timeout_seconds=5.0,
        )
    assert circuit_breakers.get_or_create("demo").snapshot().state is CircuitState.OPEN

    clock.advance(10.0)  # past recovery_timeout_seconds
    output = await runner.run(
        workflow_id="wf-1",
        step=_step(key="b", max_attempts=1),
        previous_outputs={},
        timeout_seconds=5.0,
    )
    assert output == {"attempt": 2}
    assert circuit_breakers.get_or_create("demo").snapshot().state is CircuitState.CLOSED


async def test_half_open_probe_failure_reopens_circuit() -> None:
    clock = FakeClock()
    circuit_breakers = CircuitBreakerRegistry(
        failure_threshold=1, recovery_timeout_seconds=10.0, clock=clock
    )
    inner = ScriptedInnerRunner(fail_count=None, error_type="AGENT_PROCESS_ERROR")
    runner = RetryingStepRunner(
        inner,
        retry_policy=RetryPolicy(
            base_delay_seconds=0.001, max_delay_seconds=0.005, jitter_ratio=0.0
        ),
        circuit_breakers=circuit_breakers,
    )
    with pytest.raises(StepRunnerError):
        await runner.run(
            workflow_id="wf-1",
            step=_step(key="a", max_attempts=1),
            previous_outputs={},
            timeout_seconds=5.0,
        )
    assert circuit_breakers.get_or_create("demo").snapshot().state is CircuitState.OPEN

    clock.advance(10.0)
    with pytest.raises(StepRunnerError):
        await runner.run(
            workflow_id="wf-1",
            step=_step(key="b", max_attempts=1),
            previous_outputs={},
            timeout_seconds=5.0,
        )
    assert circuit_breakers.get_or_create("demo").snapshot().state is CircuitState.OPEN
