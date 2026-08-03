"""Deterministic test-only `AgentExecutor` implementations for engine tests."""

from dataclasses import dataclass, field
from typing import Any

from app.engine.executor import StepExecutionError, StepExecutionRequest


@dataclass
class RecordingExecutor:
    """Returns a fixed JSON-compatible payload and records every call it received."""

    output: dict[str, Any] = field(default_factory=dict)
    calls: list[StepExecutionRequest] = field(default_factory=list)

    def execute(self, request: StepExecutionRequest) -> dict[str, Any]:
        self.calls.append(request)
        return dict(self.output)


@dataclass
class FailingExecutor:
    """Always raises an expected `StepExecutionError` (a handled step failure)."""

    error_message: str = "simulated step failure"
    error_type: str = "SIMULATED_FAILURE"
    calls: list[StepExecutionRequest] = field(default_factory=list)

    def execute(self, request: StepExecutionRequest) -> dict[str, Any]:
        self.calls.append(request)
        raise StepExecutionError(self.error_message, error_type=self.error_type)


@dataclass
class CrashingExecutor:
    """Always raises an unexpected (non-`StepExecutionError`) exception."""

    calls: list[StepExecutionRequest] = field(default_factory=list)

    def execute(self, request: StepExecutionRequest) -> dict[str, Any]:
        self.calls.append(request)
        raise RuntimeError("simulated unexpected crash")
