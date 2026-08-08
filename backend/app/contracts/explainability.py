"""Explainability contracts: turning an existing decision (a `RoutingDecision`,
and later a `VerificationResult`/`WorkflowPlan`) into a structured, drill-down
-able explanation.

This is a read-only transformation layer, not a second source of truth: it
sits alongside the tamper-evident `AuditEvent` hash chain (`app.audit`)
rather than replacing it — audit answers "what happened, provably";
explainability answers "why, in plain language." `RoutingDecision.explanation`
(`app.contracts.routing`, already validated non-blank) remains the quick
human-readable summary; `DecisionTrace`/`RoutingExplanation` are the
structured complement for a future explainability API/UI, never a
replacement for it.

**Strict rule, load-bearing:** every field here may describe only Keystone's
own observable decision evidence — execution counts, success rates, circuit
state, configured constraints, timing. Nothing here may expose or claim to
expose a model's hidden chain-of-thought, its internal reasoning trace, a
provider's private reasoning, credentials, prompts containing private data,
or full private file contents. `EvidenceItem.value` is checked recursively
for reserved reasoning-trace-shaped dict keys via `app.contracts.evidence_safety`
(shared with `app.contracts.verification`) — the same discipline throughout.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.contracts.evidence_safety import reject_reasoning_shaped_keys
from app.contracts.routing import RoutingDecision


class DecisionType(StrEnum):
    """What kind of Keystone decision a `DecisionTrace` explains."""

    PLANNING = "planning"
    ROUTING = "routing"
    VERIFICATION = "verification"
    RETRY = "retry"
    REROUTE = "reroute"


class EvidenceItem(BaseModel):
    """One piece of observable evidence that influenced a decision."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    description: str
    value: Any = None
    sample_size: int | None = None
    source: str | None = None

    @field_validator("kind", "description")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("value")
    @classmethod
    def _value_not_reasoning_shaped(cls, value: Any) -> Any:
        return reject_reasoning_shaped_keys(value)


class ScoreContribution(BaseModel):
    """How much one scoring factor contributed to a candidate's composite score.

    Normalized, non-negative scoring only: `raw_score`, `weight`, and
    `weighted_contribution` are each bounded to `[0.0, 1.0]`. There is no
    negative "penalty" value here — a candidate that should score worse
    because of some condition is expressed as a *low* `raw_score` (e.g.
    `0.1`, not `-0.9`), or, if the condition disqualifies the candidate
    outright rather than merely scoring it low, as an `ExclusionReason`
    instead. This keeps every number in a `ScoreContribution` directly
    comparable and averageable without sign-handling logic anywhere
    downstream.

    `weighted_contribution` is not required to equal `raw_score * weight`
    exactly: future scoring may normalize or rescale contributions (e.g.
    across factors with different evidence quality) before combining them,
    so only the bound is enforced here, not the arithmetic relationship.
    """

    model_config = ConfigDict(extra="forbid")

    factor_name: str
    raw_score: float | None = None
    weight: float
    weighted_contribution: float | None = None
    sample_size: int | None = None
    low_sample_size: bool = False

    @field_validator("factor_name")
    @classmethod
    def _factor_name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("factor_name must not be empty")
        return value

    @field_validator("raw_score", "weight", "weighted_contribution")
    @classmethod
    def _bounded_zero_to_one(cls, value: float | None) -> float | None:
        if value is not None and not 0.0 <= value <= 1.0:
            raise ValueError("must be between 0.0 and 1.0")
        return value


class ExclusionReason(BaseModel):
    """Why one candidate was excluded from consideration."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    reason_code: str
    reason_text: str

    @field_validator("candidate_id", "reason_code", "reason_text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value


class Confidence(BaseModel):
    """How confident Keystone is in a decision, and why."""

    model_config = ConfigDict(extra="forbid")

    value: float
    basis: str
    sample_size: int | None = None
    low_sample_size: bool = False

    @field_validator("value")
    @classmethod
    def _value_bounded(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence value must be between 0 and 1")
        return value

    @field_validator("basis")
    @classmethod
    def _basis_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("basis must not be empty")
        return value


class CounterfactualCondition(BaseModel):
    """What would have had to be different for a different outcome."""

    model_config = ConfigDict(extra="forbid")

    description: str
    would_change_outcome_to: str | None = None

    @field_validator("description")
    @classmethod
    def _description_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("description must not be empty")
        return value


class DecisionTrace(BaseModel):
    """A structured, human-readable explanation of one Keystone decision."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str
    decision_type: DecisionType
    subject_id: str
    summary: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    confidence: Confidence | None = None
    counterfactuals: list[CounterfactualCondition] = Field(default_factory=list)
    created_at: datetime

    @field_validator("decision_id", "subject_id")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("summary")
    @classmethod
    def _summary_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary must not be empty")
        return value


class RoutingExplanation(BaseModel):
    """A `DecisionTrace` specifically for a `RoutingDecision`, with the full
    per-candidate score breakdown and exclusion reasons alongside the
    decision it explains. Wraps `RoutingDecision` rather than duplicating it."""

    model_config = ConfigDict(extra="forbid")

    decision: RoutingDecision
    trace: DecisionTrace
    score_contributions: dict[str, list[ScoreContribution]] = Field(default_factory=dict)
    exclusions: list[ExclusionReason] = Field(default_factory=list)


__all__ = [
    "Confidence",
    "CounterfactualCondition",
    "DecisionTrace",
    "DecisionType",
    "EvidenceItem",
    "ExclusionReason",
    "RoutingExplanation",
    "ScoreContribution",
]
