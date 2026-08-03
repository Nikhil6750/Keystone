"""Deterministic test-only `CompensationExecutor` implementations."""

from dataclasses import dataclass, field
from typing import Any

from app.engine.compensation_context import CompensationRequest
from app.engine.compensation_exceptions import CompensationExecutionError


@dataclass
class RecordingCompensationHandler:
    """Returns a fixed JSON-compatible payload and records every call it received."""

    output: dict[str, Any] = field(default_factory=dict)
    calls: list[CompensationRequest] = field(default_factory=list)

    def compensate(self, request: CompensationRequest) -> dict[str, Any]:
        self.calls.append(request)
        return dict(self.output)


@dataclass
class FailingCompensationHandler:
    """Always raises an expected `CompensationExecutionError`."""

    error_message: str = "simulated compensation failure"
    calls: list[CompensationRequest] = field(default_factory=list)

    def compensate(self, request: CompensationRequest) -> dict[str, Any]:
        self.calls.append(request)
        raise CompensationExecutionError(self.error_message)


@dataclass
class CrashingCompensationHandler:
    """Always raises an unexpected (non-`CompensationError`) exception."""

    calls: list[CompensationRequest] = field(default_factory=list)

    def compensate(self, request: CompensationRequest) -> dict[str, Any]:
        self.calls.append(request)
        raise RuntimeError("simulated unexpected compensation crash")
