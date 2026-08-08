"""Explainable agent-routing contracts.

Data shapes only — Stage 4 implements the classifier, scorer and router
logic that produces these. Every `RoutingDecision` carries a human-readable
`explanation` because routing decisions must never be a black box (see
`docs/contracts.md`). `RoutingConstraints` gives `RoutingRequest.constraints`
a typed, validated shape instead of a schema-less `dict[str, Any]`, so every
recognized constraint is documented and every combination is either valid or
rejected outright — never silently coerced.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.contracts.adapter import RepositoryMetadata
from app.contracts.enums import AgentCapability


class RoutingConstraints(BaseModel):
    """Structured, explainable routing constraints.

    Replaces an earlier schema-less `dict[str, Any]`: every recognized
    constraint now has a typed, validated, documented shape instead of an
    undocumented key vocabulary a caller had to guess at. Contains no
    provider-specific settings — provider detail belongs in
    `AgentExecutionRequest.metadata`, never here.
    """

    model_config = ConfigDict(extra="forbid")

    required_capabilities: list[str] = Field(default_factory=list)
    excluded_agent_types: list[str] = Field(default_factory=list)
    preferred_agent_types: list[str] = Field(default_factory=list)
    max_cost_usd: float | None = None
    max_latency_ms: float | None = None
    minimum_reliability: float | None = None
    allow_parallel: bool = False
    consensus_size: int | None = None

    @field_validator("required_capabilities", "excluded_agent_types", "preferred_agent_types")
    @classmethod
    def _entries_not_blank(cls, value: list[str]) -> list[str]:
        if any(not entry.strip() for entry in value):
            raise ValueError("entries must not be blank")
        return value

    @field_validator("required_capabilities", "excluded_agent_types", "preferred_agent_types")
    @classmethod
    def _entries_no_duplicates(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("duplicate entries are not allowed")
        return value

    @field_validator("max_cost_usd")
    @classmethod
    def _max_cost_nonnegative(cls, value: float | None) -> float | None:
        if value is not None and value < 0:
            raise ValueError("max_cost_usd must not be negative")
        return value

    @field_validator("max_latency_ms")
    @classmethod
    def _max_latency_positive(cls, value: float | None) -> float | None:
        if value is not None and value <= 0:
            raise ValueError("max_latency_ms must be positive")
        return value

    @field_validator("minimum_reliability")
    @classmethod
    def _minimum_reliability_bounded(cls, value: float | None) -> float | None:
        if value is not None and not 0.0 <= value <= 1.0:
            raise ValueError("minimum_reliability must be between 0 and 1")
        return value

    @field_validator("consensus_size")
    @classmethod
    def _consensus_size_valid(cls, value: int | None) -> int | None:
        if value is not None and value < 2:
            raise ValueError("consensus_size must be at least 2")
        return value

    @model_validator(mode="after")
    def _consensus_requires_parallel(self) -> "RoutingConstraints":
        if self.consensus_size is not None and not self.allow_parallel:
            raise ValueError("consensus_size is only allowed when allow_parallel is True")
        return self


class RoutingRequest(BaseModel):
    """A request to select an agent for one task."""

    model_config = ConfigDict(extra="forbid")

    task_type: str
    repository: RepositoryMetadata | None = None
    required_capabilities: list[AgentCapability] = Field(default_factory=list)
    candidate_agent_types: list[str] | None = None
    manual_override_agent_type: str | None = None
    constraints: RoutingConstraints = Field(default_factory=RoutingConstraints)

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

    @model_validator(mode="after")
    def _eligibility_consistency(self) -> "RoutingCandidateScore":
        """Enforce the `eligible` <-> `excluded_reason` pairing. Never rewrites
        the input to make it consistent — an inconsistent combination is a
        caller bug and must fail loudly."""
        if self.eligible and self.excluded_reason is not None:
            raise ValueError("excluded_reason must be None when eligible is True")
        if not self.eligible and not (self.excluded_reason and self.excluded_reason.strip()):
            raise ValueError(
                "excluded_reason is required and must not be blank when eligible is False"
            )
        return self


class RoutingDecision(BaseModel):
    """The outcome of one routing evaluation, always explainable.

    `selected_agent_types` is an additive field (Stage 4B) alongside the
    original `selected_agent_type`, kept for backward compatibility: it
    carries the full ordered selected set for parallel/consensus routing
    (`RoutingConstraints.allow_parallel`), while `selected_agent_type`
    remains the single deterministic primary — the first entry of
    `selected_agent_types` whenever both are populated. Single-selection
    decisions populate both with one matching entry; a decision with no
    selection (no eligible candidates) leaves both empty/`None`.
    """

    model_config = ConfigDict(from_attributes=True)

    task_type: str
    selected_agent_type: str | None
    selected_agent_types: list[str] = Field(default_factory=list)
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

    @model_validator(mode="after")
    def _manual_override_requires_selection(self) -> "RoutingDecision":
        """A manual override with no selected agent is a contradiction — never
        silently accepted or rewritten."""
        if self.manual_override and not (
            self.selected_agent_type and self.selected_agent_type.strip()
        ):
            raise ValueError("selected_agent_type is required when manual_override is True")
        return self

    @model_validator(mode="after")
    def _selected_agent_types_consistency(self) -> "RoutingDecision":
        """`selected_agent_types` must never contradict `selected_agent_type`
        — never silently reconciled, only rejected."""
        if self.selected_agent_type is None and self.selected_agent_types:
            raise ValueError("selected_agent_types must be empty when selected_agent_type is None")
        if (
            self.selected_agent_type is not None
            and self.selected_agent_types
            and self.selected_agent_type not in self.selected_agent_types
        ):
            raise ValueError(
                "selected_agent_type must be included in selected_agent_types when both are set"
            )
        return self

    @model_validator(mode="after")
    def _selected_agent_types_unique(self) -> "RoutingDecision":
        """A duplicate entry would mean the same runtime was selected twice
        for one decision — always a caller/producer bug, never silently
        deduplicated."""
        if len(self.selected_agent_types) != len(set(self.selected_agent_types)):
            raise ValueError("selected_agent_types must not contain duplicates")
        return self


__all__ = ["RoutingCandidateScore", "RoutingConstraints", "RoutingDecision", "RoutingRequest"]
