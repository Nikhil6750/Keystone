"""Agent passport contracts: objective, outcome-based evidence profiles.

Data shapes only — Stage 5 implements aggregation and persistence. Every
metric here is derived from measurable execution outcomes (tests passed,
build passed, execution failed, timed out, cancelled); this contract
deliberately has no field for a subjective quality score.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AgentPassportMetricBucket(BaseModel):
    """Execution counts and latency for one dimension (a task type, a repository, ...)."""

    model_config = ConfigDict(from_attributes=True)

    execution_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    median_latency_ms: float | None = None
    low_sample_size: bool = False


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
