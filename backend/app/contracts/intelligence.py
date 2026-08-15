"""Stage 9E Domain Contracts: Engineering Intelligence Graph.

The Engineering Intelligence Graph is a deterministic *projection* of
evidence Keystone already produces and persists elsewhere (Stage 8C.1
orchestration, Stage 9C Verified Skill Foundry, Stage 9D Software Quality
Factory). It owns none of that evidence's authority: a node/edge here only
ever references a canonical identifier from an existing system (a
`workflow_id`, `step_id`/attempt id, `agent_type`, `skill_id`/`version`,
Stage 9D `run_id`/`gate_id`) plus small, normalized, factual metadata --
never a second copy of the underlying record, and never a model's internal
reasoning (see `app.contracts.evidence_safety`).

Provider neutrality: `agent_type` is treated everywhere as an opaque,
stable string identifier from the existing agent registry -- nothing here
branches on a specific provider name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class IntelligenceNodeType(StrEnum):
    """Every graph entity type the Engineering Intelligence Graph projects."""

    WORKFLOW = "WORKFLOW"
    TASK = "TASK"
    ATTEMPT = "ATTEMPT"
    AGENT = "AGENT"
    SKILL_VERSION = "SKILL_VERSION"
    QUALITY_RUN = "QUALITY_RUN"
    QUALITY_GATE = "QUALITY_GATE"
    OUTCOME = "OUTCOME"
    FAILURE = "FAILURE"
    RECOVERY_ATTEMPT = "RECOVERY_ATTEMPT"


class IntelligenceEdgeType(StrEnum):
    """Every typed relationship the Engineering Intelligence Graph projects."""

    WORKFLOW_CONTAINS_TASK = "WORKFLOW_CONTAINS_TASK"
    TASK_EXECUTED_BY_AGENT = "TASK_EXECUTED_BY_AGENT"
    TASK_USED_SKILL = "TASK_USED_SKILL"
    TASK_HAS_ATTEMPT = "TASK_HAS_ATTEMPT"
    ATTEMPT_PRODUCED_OUTCOME = "ATTEMPT_PRODUCED_OUTCOME"
    ATTEMPT_HAS_QUALITY_RUN = "ATTEMPT_HAS_QUALITY_RUN"
    QUALITY_RUN_EXECUTED_GATE = "QUALITY_RUN_EXECUTED_GATE"
    ATTEMPT_FAILED_WITH = "ATTEMPT_FAILED_WITH"
    ATTEMPT_RECOVERED_BY = "ATTEMPT_RECOVERED_BY"


class FailureAttributionCategory(StrEnum):
    """Evidence-based classification of why a task/attempt did not succeed.

    `UNKNOWN` is not a fallback to avoid -- it is the honest answer when
    persisted evidence does not directly support a more specific category.
    Never inferred from speculation about provider/model behavior.
    """

    EXECUTION_FAILURE = "execution_failure"
    TIMEOUT = "timeout"
    QUALITY_GATE_FAILURE = "quality_gate_failure"
    INVALID_CONFIGURATION = "invalid_configuration"
    RECOVERY_EXHAUSTION = "recovery_exhaustion"
    AGENT_UNAVAILABLE = "agent_unavailable"
    SKILL_VERIFICATION_FAILURE = "skill_verification_failure"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class IntelligenceNode:
    """One graph entity. `canonical_id` is the id of the real, authoritative
    record this node projects (a `workflow_id`, `StepAttempt.id`,
    `agent_type`, `skill_id:version`, Stage 9D `run_id`, etc.) -- `node_id`
    is deterministically derived from `(node_type, canonical_id)` so
    replaying the same source evidence always produces the same node_id
    (idempotent ingestion, see `app.engine.intelligence.builder`)."""

    node_id: str
    node_type: IntelligenceNodeType
    canonical_id: str
    label: str
    workflow_id: str | None = None
    agent_type: str | None = None
    task_type: str | None = None
    skill_id: str | None = None
    skill_version: str | None = None
    status: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class IntelligenceEdge:
    """One typed, directed relationship between two `IntelligenceNode`s.
    `edge_id` is deterministically derived from
    `(edge_type, source_node_id, target_node_id)` -- the same canonical
    relationship observed twice always produces the same edge_id, so
    replaying source evidence can never create a duplicate edge."""

    edge_id: str
    edge_type: IntelligenceEdgeType
    source_node_id: str
    target_node_id: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class FailureAttribution:
    """Evidence-based attribution of one failure observation to a category.

    `is_known` is `False` whenever persisted evidence does not directly
    support a specific category -- `category` is then `UNKNOWN`, never a
    guessed, more specific one. `evidence_ids` names the canonical
    identifiers (attempt id, quality run id, gate id) a caller can use to
    retrieve the underlying record; this never carries the record's content
    itself."""

    attribution_id: str
    attempt_node_id: str
    category: FailureAttributionCategory
    is_known: bool
    explanation: str
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    workflow_id: str | None = None
    agent_type: str | None = None
    task_type: str | None = None
    skill_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# Below this sample size, a computed rate is exposed alongside its raw
# counts but flagged `sample_size_is_low=True` -- callers must not treat a
# rate from a handful of observations as a strong statistical signal.
LOW_SAMPLE_SIZE_THRESHOLD = 5


@dataclass(frozen=True)
class TaskReliabilityObservation:
    """Deterministic, evidence-backed reliability signal for one task type
    (or all task types when `task_type` is `None`). Always exposes raw
    counts alongside any derived rate -- never just one opaque number."""

    task_type: str | None
    attempt_count: int
    success_count: int
    failure_count: int
    recovery_count: int
    quality_rejection_count: int

    @property
    def success_rate(self) -> float | None:
        if self.attempt_count == 0:
            return None
        return self.success_count / self.attempt_count

    @property
    def sample_size_is_low(self) -> bool:
        return self.attempt_count < LOW_SAMPLE_SIZE_THRESHOLD


@dataclass(frozen=True)
class AgentReliabilityObservation:
    """Deterministic, evidence-backed reliability signal for one agent
    (optionally scoped to a task type)."""

    agent_type: str
    task_type: str | None
    observed_executions: int
    successful_executions: int
    failed_executions: int
    recovery_count: int
    quality_verified_successes: int

    @property
    def success_rate(self) -> float | None:
        if self.observed_executions == 0:
            return None
        return self.successful_executions / self.observed_executions

    @property
    def sample_size_is_low(self) -> bool:
        return self.observed_executions < LOW_SAMPLE_SIZE_THRESHOLD


@dataclass(frozen=True)
class SkillReliabilityObservation:
    """Deterministic, evidence-backed reliability signal for one skill
    version (optionally scoped to a task type)."""

    skill_id: str
    skill_version: str | None
    task_type: str | None
    uses: int
    successful_uses: int
    failed_uses: int
    quality_verified_uses: int

    @property
    def success_rate(self) -> float | None:
        if self.uses == 0:
            return None
        return self.successful_uses / self.uses

    @property
    def sample_size_is_low(self) -> bool:
        return self.uses < LOW_SAMPLE_SIZE_THRESHOLD


@dataclass(frozen=True)
class QualityGateIntelligence:
    """Deterministic, evidence-backed aggregate over Stage 9D quality gate
    results reachable through the graph (optionally scoped to task/agent/
    skill context)."""

    task_type: str | None
    agent_type: str | None
    skill_id: str | None
    total_gate_results: int
    passed_count: int
    failed_count: int
    error_count: int
    skipped_count: int
    most_frequent_failed_gate_types: tuple[tuple[str, int], ...] = field(default_factory=tuple)

    @property
    def sample_size_is_low(self) -> bool:
        return self.total_gate_results < LOW_SAMPLE_SIZE_THRESHOLD


__all__ = [
    "LOW_SAMPLE_SIZE_THRESHOLD",
    "AgentReliabilityObservation",
    "FailureAttribution",
    "FailureAttributionCategory",
    "IntelligenceEdge",
    "IntelligenceEdgeType",
    "IntelligenceNode",
    "IntelligenceNodeType",
    "QualityGateIntelligence",
    "SkillReliabilityObservation",
    "TaskReliabilityObservation",
]
