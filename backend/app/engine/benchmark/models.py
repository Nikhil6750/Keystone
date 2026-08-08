"""Stage 7A Benchmark Engine domain models.

Provider-neutral, deterministic representations of benchmark suites, benchmark
cases, execution observations, execution results, and metrics.

REUSES Stage 4E verification contracts and evaluators 100%:
- `ExpectedOutcome` (`app.contracts.planning`)
- `ObservedOutcome` (`app.engine.verification.evaluators`)
- `VerificationResult`, `VerificationStatus` (`app.contracts.verification`)
- `reject_reasoning_shaped_keys()` (`app.contracts.evidence_safety`)
- `AgentExecutionStatus` (`app.contracts.enums`)
- `FailureCategory` (`app.contracts.errors`)
"""

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.contracts.enums import AgentExecutionStatus
from app.contracts.errors import FailureCategory
from app.contracts.evidence_safety import reject_reasoning_shaped_keys
from app.contracts.planning import ExpectedOutcome
from app.contracts.verification import VerificationResult, VerificationStatus
from app.engine.benchmark.errors import (
    MalformedBenchmarkCaseError,
    MalformedBenchmarkObservationError,
    MalformedBenchmarkSuiteError,
)
from app.engine.verification.evaluators import ObservedOutcome

MAX_BENCHMARK_REPEAT_COUNT = 20
_ABSOLUTE_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _looks_like_unsafe_repository_id(value: str) -> bool:
    """True if `value` looks like an absolute filesystem path or contains a `..`
    traversal segment."""
    if value.startswith("/") or value.startswith("\\"):
        return True
    if _ABSOLUTE_DRIVE_PATH_RE.match(value):
        return True
    segments = re.split(r"[\\/]", value)
    return ".." in segments


@dataclass(frozen=True)
class BenchmarkCase:
    """One objective benchmark task definition.

    Reuses Stage 4E's `ExpectedOutcome` directly -- no duplicate evaluator schema.
    Rejects reasoning-shaped keys in `input_payload` and `metadata`. Rejects
    absolute filesystem paths in `repository_id`.
    """

    case_id: str
    task_type: str
    expected_outcome: ExpectedOutcome
    input_payload: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 30.0
    repository_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise MalformedBenchmarkCaseError("case_id must not be blank")
        if not self.task_type.strip():
            raise MalformedBenchmarkCaseError("task_type must not be blank")
        if self.timeout_seconds <= 0 or not math.isfinite(self.timeout_seconds):
            raise MalformedBenchmarkCaseError("timeout_seconds must be positive and finite")

        if self.repository_id is not None:
            if not self.repository_id.strip():
                raise MalformedBenchmarkCaseError("repository_id must not be blank if provided")
            if _looks_like_unsafe_repository_id(self.repository_id):
                raise MalformedBenchmarkCaseError(
                    f"repository_id must not look like an absolute filesystem path: "
                    f"{self.repository_id!r}"
                )

        try:
            reject_reasoning_shaped_keys(self.input_payload)
            reject_reasoning_shaped_keys(self.metadata)
        except ValueError as exc:
            raise MalformedBenchmarkCaseError(str(exc)) from exc


@dataclass(frozen=True)
class BenchmarkSuite:
    """An immutable, reproducible collection of benchmark cases.

    Enforces unique case IDs and bounds repetition counts (1 to
    `MAX_BENCHMARK_REPEAT_COUNT`).
    """

    suite_id: str
    name: str
    cases: tuple[BenchmarkCase, ...]
    description: str | None = None
    repeat_count: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.suite_id.strip():
            raise MalformedBenchmarkSuiteError("suite_id must not be blank")
        if not self.name.strip():
            raise MalformedBenchmarkSuiteError("name must not be blank")
        if not self.cases:
            raise MalformedBenchmarkSuiteError("a benchmark suite must contain at least one case")
        if not 1 <= self.repeat_count <= MAX_BENCHMARK_REPEAT_COUNT:
            raise MalformedBenchmarkSuiteError(
                f"repeat_count must be between 1 and {MAX_BENCHMARK_REPEAT_COUNT}"
            )

        seen_case_ids: set[str] = set()
        for case in self.cases:
            if case.case_id in seen_case_ids:
                raise MalformedBenchmarkSuiteError(
                    f"duplicate case_id '{case.case_id}' in benchmark suite"
                )
            seen_case_ids.add(case.case_id)

        try:
            reject_reasoning_shaped_keys(self.metadata)
        except ValueError as exc:
            raise MalformedBenchmarkSuiteError(str(exc)) from exc


@dataclass(frozen=True)
class BenchmarkExecutionObservation:
    """The raw, observable data returned by a `BenchmarkExecutor` execution.

    Contains no hidden reasoning. Reuses Stage 4E's `ObservedOutcome` for evidence.
    """

    agent_type: str
    execution_status: AgentExecutionStatus
    duration_ms: float
    observed_outcome: ObservedOutcome
    failure_category: FailureCategory | None = None
    attempt_number: int = 1
    cost_usd: float | None = None

    def __post_init__(self) -> None:
        if not self.agent_type.strip():
            raise MalformedBenchmarkObservationError("agent_type must not be blank")
        if not math.isfinite(self.duration_ms) or self.duration_ms < 0:
            raise MalformedBenchmarkObservationError("duration_ms must be finite and non-negative")
        if self.attempt_number < 1:
            raise MalformedBenchmarkObservationError("attempt_number must be at least 1")
        if self.cost_usd is not None and (not math.isfinite(self.cost_usd) or self.cost_usd < 0):
            raise MalformedBenchmarkObservationError("cost_usd must be finite and non-negative")

        status = self.execution_status
        category = self.failure_category
        if status is AgentExecutionStatus.SUCCEEDED and category is not None:
            raise MalformedBenchmarkObservationError(
                "failure_category must be None when execution_status is SUCCEEDED"
            )
        if status is AgentExecutionStatus.FAILED and category is None:
            raise MalformedBenchmarkObservationError(
                "failure_category is required when execution_status is FAILED"
            )
        if status is AgentExecutionStatus.CANCELLED and category is not FailureCategory.CANCELLED:
            raise MalformedBenchmarkObservationError(
                "failure_category must be CANCELLED when execution_status is CANCELLED"
            )
        if status is AgentExecutionStatus.TIMED_OUT and category is not FailureCategory.TIMEOUT:
            raise MalformedBenchmarkObservationError(
                "failure_category must be TIMEOUT when execution_status is TIMED_OUT"
            )


@dataclass(frozen=True)
class BenchmarkExecutionResult:
    """The full, observable result of executing one agent on one benchmark case for
    one repetition, verified via Stage 4E.
    """

    suite_id: str
    case_id: str
    agent_type: str
    repetition: int
    task_type: str
    execution_status: AgentExecutionStatus
    verification_status: VerificationStatus
    verification_result: VerificationResult
    duration_ms: float
    repository_id: str | None = None
    failure_category: FailureCategory | None = None
    cost_usd: float | None = None
    created_at: datetime | None = None


__all__ = [
    "MAX_BENCHMARK_REPEAT_COUNT",
    "BenchmarkCase",
    "BenchmarkExecutionObservation",
    "BenchmarkExecutionResult",
    "BenchmarkSuite",
]
