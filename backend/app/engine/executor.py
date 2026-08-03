"""Agent executor contract: the interface real (Phase 3) and test executors satisfy."""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class StepExecutionRequest:
    """Everything an executor needs to run one workflow step."""

    workflow_id: str
    step_id: str
    step_name: str
    agent_type: str
    step_input: dict[str, Any]
    workflow_input: dict[str, Any]
    previous_step_outputs: dict[str, dict[str, Any]]


class StepExecutionError(Exception):
    """Raised by an executor for an expected, handleable step failure.

    The engine catches this and persists the step/attempt/workflow as FAILED.
    When `retryable` is `True` and the step has attempts remaining and its
    circuit breaker permits another call, the engine retries instead of
    failing immediately; `retryable=False` (the default) preserves the
    original Phase 2 behavior of stopping immediately without retrying.
    """

    def __init__(
        self,
        message: str,
        *,
        error_type: str = "STEP_EXECUTION_FAILED",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.retryable = retryable


class AgentExecutor(Protocol):
    """One executable agent implementation for a given `agent_type`."""

    def execute(self, request: StepExecutionRequest) -> dict[str, Any]:
        """Run the step and return a JSON-compatible output payload."""
        ...
