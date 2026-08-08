"""Agent passport contracts: objective, outcome-based evidence profiles.

Data shapes only — Stage 5 implements aggregation and persistence. Every
metric here is derived from measurable execution outcomes (tests passed,
build passed, execution failed, timed out, cancelled); this contract
deliberately has no field for a subjective quality score.
"""

import math
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AgentPassportMetricBucket(BaseModel):
    """Execution counts and latency for one dimension (a task type, a repository, ...).

    Validated so that every consumer (the Stage 4B Router in particular) can
    trust these values without re-checking them: counts are non-negative,
    `success_count` can never exceed `execution_count`, and `median_latency_ms`
    — when present — is always finite and non-negative. A malformed bucket
    (e.g. from a buggy future aggregation implementation) is rejected here,
    at construction, rather than silently accepted and left for a downstream
    consumer to (maybe) defend against.
    """

    model_config = ConfigDict(from_attributes=True)

    execution_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    median_latency_ms: float | None = None
    low_sample_size: bool = False

    @field_validator("execution_count", "success_count", "failure_count")
    @classmethod
    def _counts_not_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("must not be negative")
        return value

    @field_validator("median_latency_ms")
    @classmethod
    def _latency_finite_and_nonnegative(cls, value: float | None) -> float | None:
        if value is not None:
            if not math.isfinite(value):
                raise ValueError("median_latency_ms must be finite (not NaN or infinite)")
            if value < 0:
                raise ValueError("median_latency_ms must not be negative")
        return value

    @model_validator(mode="after")
    def _success_count_within_execution_count(self) -> "AgentPassportMetricBucket":
        if self.success_count > self.execution_count:
            raise ValueError("success_count must not exceed execution_count")
        return self


class AgentPassport(BaseModel):
    """One agent type's objective, recomputable execution-evidence profile."""

    model_config = ConfigDict(from_attributes=True)

    agent_type: str
    execution_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    cancellation_count: int = 0
    retry_count: int = 0
    median_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    failure_categories: dict[str, int] = Field(default_factory=dict)
    task_type_metrics: dict[str, AgentPassportMetricBucket] = Field(default_factory=dict)
    repository_metrics: dict[str, AgentPassportMetricBucket] = Field(default_factory=dict)
    low_sample_size: bool = False
    last_verified_at: datetime | None = None
    last_succeeded_at: datetime | None = None
    updated_at: datetime


__all__ = ["AgentPassport", "AgentPassportMetricBucket"]
