"""A `StepRunner` decorator adding retry, exponential backoff, and
circuit-breaker awareness — without any `GraphScheduler` changes, exactly as
promised in Stage 2's `scheduler.py` docstring.

Reuses the existing `RetryPolicy` (its delay computation, not its blocking
`Sleeper`, which uses `time.sleep` and would block the event loop) and
`CircuitBreakerRegistry` (`app.resilience`) rather than duplicating
retry/backoff/circuit-breaker logic a second time — the same classification
shape (retryable vs. not, circuit-breaker-aware, bounded by attempts) as the
live `WorkflowEngine`'s retry loop.
"""

import asyncio
from typing import Any

from app.contracts.errors import RETRYABLE_FAILURE_CATEGORIES, classify_legacy_error_type
from app.contracts.workflow import WorkflowStepDefinition
from app.engine.workflow.exceptions import StepRunnerError
from app.engine.workflow.runner import StepRunner
from app.resilience.circuit_breaker import (
    CircuitBreakerOpenError,
    CircuitBreakerRegistry,
    CircuitState,
)
from app.resilience.retry import RetryPolicy


class RetryingStepRunner:
    """Wraps a `StepRunner`, retrying classified-retryable failures up to
    `WorkflowStepDefinition.max_attempts`, honoring a per-agent-type circuit breaker.

    Never retries a non-retryable failure category (authentication,
    validation, cancellation, an already-open circuit, or an internal
    error), never exceeds `step.max_attempts`, and never calls the wrapped
    runner again once its circuit breaker is open.
    """

    def __init__(
        self,
        inner: StepRunner,
        *,
        retry_policy: RetryPolicy,
        circuit_breakers: CircuitBreakerRegistry,
    ) -> None:
        self._inner = inner
        self._retry_policy = retry_policy
        self._circuit_breakers = circuit_breakers

    async def run(
        self,
        *,
        workflow_id: str,
        step: WorkflowStepDefinition,
        previous_outputs: dict[str, dict[str, Any]],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        breaker = self._circuit_breakers.get_or_create(step.agent_type)
        attempt_number = 0

        while True:
            attempt_number += 1
            try:
                breaker.before_call()
            except CircuitBreakerOpenError as exc:
                raise StepRunnerError(str(exc), error_type="CIRCUIT_BREAKER_OPEN") from exc

            try:
                output = await self._inner.run(
                    workflow_id=workflow_id,
                    step=step,
                    previous_outputs=previous_outputs,
                    timeout_seconds=timeout_seconds,
                )
            except StepRunnerError as exc:
                category = classify_legacy_error_type(exc.error_type)
                retryable = category in RETRYABLE_FAILURE_CATEGORIES
                if retryable:
                    breaker.record_failure()
                circuit_open_now = breaker.snapshot().state is CircuitState.OPEN
                can_retry = (
                    retryable and attempt_number < step.max_attempts and not circuit_open_now
                )
                if not can_retry:
                    raise
                delay = self._retry_policy.compute_delay(attempt_number)
                await asyncio.sleep(delay)
                continue

            breaker.record_success()
            return output


__all__ = ["RetryingStepRunner"]
