"""Explainable agent-routing contracts.

Data shapes only — Stage 4 implements the classifier, scorer and router
logic that produces these. Every `RoutingDecision` carries a human-readable
`explanation` because routing decisions must never be a black box (see
`docs/contracts.md`).
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.contracts.adapter import RepositoryMetadata
from app.contracts.enums import AgentCapability


class RoutingRequest(BaseModel):
    """A request to select an agent for one task."""

    model_config = ConfigDict(extra="forbid")

    task_type: str
    repository: RepositoryMetadata | None = None
    required_capabilities: list[AgentCapability] = Field(default_factory=list)
    candidate_agent_types: list[str] | None = None
    manual_override_agent_type: str | None = None
    constraints: dict[str, Any] = Field(default_factory=dict)

    @field_validator("task_type")
    @classmethod
    def _task_type_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("task_type must not be empty")
        return value


class RoutingCandidateScore(BaseModel):
    """One candidate agent's evaluated fitness for a routing request.

    Missing historical data must never be silently treated as perfect
    performance — callers should leave the relevant score field `None` and
    set `low_sample_size=True` rather than defaulting to a high score.
    """

    model_config = ConfigDict(from_attributes=True)

    agent_type: str
    eligible: bool
    excluded_reason: str | None = None
    capability_match: bool
    reliability_score: float | None = None
    latency_score: float | None = None
    cost_score: float | None = None
    repository_score: float | None = None
    task_type_score: float | None = None
    composite_score: float | None = None
    sample_size: int = 0
    low_sample_size: bool = False
    evidence: dict[str, Any] = Field(default_factory=dict)


class RoutingDecision(BaseModel):
    """The outcome of one routing evaluation, always explainable."""

    model_config = ConfigDict(from_attributes=True)

    task_type: str
    selected_agent_type: str | None
    candidates: list[RoutingCandidateScore] = Field(default_factory=list)
    fallback_order: list[str] = Field(default_factory=list)
    manual_override: bool = False
    confidence: float | None = None
    explanation: str
    decided_at: datetime

    @field_validator("explanation")
    @classmethod
    def _explanation_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("explanation must not be empty")
        return value


__all__ = ["RoutingCandidateScore", "RoutingDecision", "RoutingRequest"]
