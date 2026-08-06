"""Objective agent-benchmarking contracts.

Data shapes only — Stage 7 implements the benchmark runner and evaluators.
`evaluator_type` is always one of `BenchmarkEvaluatorType`'s objective
evaluators (exact match, JSON schema, exit code, unit test, build, lint,
type check, file diff, human-reviewed) — this contract has no field for a
subjective model ranking.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.contracts.adapter import AgentUsage
from app.contracts.enums import BenchmarkEvaluatorType
from app.contracts.errors import FailureCategory


class BenchmarkTask(BaseModel):
    """One task within a benchmark definition."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    input_payload: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] | None = None
    evaluator_type: BenchmarkEvaluatorType

    @field_validator("task_id")
    @classmethod
    def _task_id_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("task_id must not be empty")
        return value


class BenchmarkDefinition(BaseModel):
    """A reproducible comparison of candidate agents across a set of tasks."""

    model_config = ConfigDict(extra="forbid")

    benchmark_id: str
    name: str
    description: str | None = None
    tasks: list[BenchmarkTask] = Field(default_factory=list)
    candidate_agent_types: list[str] = Field(default_factory=list)
    repeat_count: int = 1
    warm_up: bool = False
    timeout_seconds: float

    @field_validator("benchmark_id", "name")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("repeat_count")
    @classmethod
    def _repeat_count_valid(cls, value: int) -> int:
        if value < 1:
            raise ValueError("repeat_count must be at least 1")
        return value

    @field_validator("timeout_seconds")
    @classmethod
    def _timeout_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("timeout_seconds must be positive")
        return value

    @field_validator("tasks")
    @classmethod
    def _tasks_not_empty(cls, value: list[BenchmarkTask]) -> list[BenchmarkTask]:
        if not value:
            raise ValueError("a benchmark must declare at least one task")
        return value

    @field_validator("candidate_agent_types")
    @classmethod
    def _candidates_not_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("a benchmark must declare at least one candidate agent type")
        return value


class BenchmarkResult(BaseModel):
    """One agent's outcome on one task, for one run attempt."""

    model_config = ConfigDict(from_attributes=True)

    benchmark_id: str
    run_id: str
    agent_type: str
    task_id: str
    attempt_number: int = 1
    success: bool
    failure_category: FailureCategory | None = None
    duration_ms: float
    is_warm_up: bool = False
    output_payload: dict[str, Any] | None = None
    usage: AgentUsage | None = None
    environment: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


__all__ = ["BenchmarkDefinition", "BenchmarkResult", "BenchmarkTask"]
