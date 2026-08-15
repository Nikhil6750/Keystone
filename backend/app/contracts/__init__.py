"""Canonical, provider-neutral domain contracts shared across the engine, API,
CLI and extension clients.

This package is additive: it does not replace `app.schemas` (the live API
request/response contract) or `app.models.enums` (the live persisted
workflow/step status enums). Those remain the source of truth for behavior
that already ships. `app.contracts` defines the vNext shapes — the
provider-neutral `AgentAdapter` protocol, the DAG-aware workflow definition,
routing, agent-passport, knowledge, benchmark, planning, verification and
explainability contracts — that later stages incrementally wire into
persistence, the engine and the API layer.

See `docs/contracts.md` for ownership, dependency direction, and the
generated JSON Schema locations under `backend/contracts/schemas/`.
"""

from app.contracts.adapter import (
    AgentAdapter,
    AgentDescriptor,
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentUsage,
    RepositoryMetadata,
)
from app.contracts.benchmark import BenchmarkDefinition, BenchmarkResult, BenchmarkTask
from app.contracts.enums import (
    AgentCapability,
    AgentExecutionStatus,
    AgentStatus,
    BenchmarkEvaluatorType,
    RuntimeKind,
)
from app.contracts.errors import (
    RETRYABLE_FAILURE_CATEGORIES,
    FailureCategory,
    classify_legacy_error_type,
)
from app.contracts.explainability import (
    Confidence,
    CounterfactualCondition,
    DecisionTrace,
    DecisionType,
    EvidenceItem,
    ExclusionReason,
    RoutingExplanation,
    ScoreContribution,
)
from app.contracts.intelligence import (
    LOW_SAMPLE_SIZE_THRESHOLD,
    AgentReliabilityObservation,
    FailureAttribution,
    FailureAttributionCategory,
    IntelligenceEdge,
    IntelligenceEdgeType,
    IntelligenceNode,
    IntelligenceNodeType,
    QualityGateIntelligence,
    SkillReliabilityObservation,
    TaskReliabilityObservation,
)
from app.contracts.knowledge import KnowledgeDocument, KnowledgeSearchResult
from app.contracts.passports import AgentPassport, AgentPassportMetricBucket
from app.contracts.planning import ExpectedOutcome, PlanningRequest, TaskSpec, WorkflowPlan
from app.contracts.quality import (
    QualityContractValidationError,
    QualityEvidence,
    QualityExecutionContext,
    QualityGateResult,
    QualityGateSpec,
    QualityGateStatus,
    QualityGateType,
    QualityProfile,
    QualityRepairPacket,
    QualityRun,
    QualityVerdict,
    QualityVerdictStatus,
)
from app.contracts.routing import (
    RoutingCandidateScore,
    RoutingConstraints,
    RoutingDecision,
    RoutingRequest,
)
from app.contracts.skills import (
    SkillAssignment,
    SkillCategory,
    SkillContract,
    SkillContractValidationError,
    SkillExecutionTrace,
    SkillStatus,
)
from app.contracts.verification import VerificationEvidence, VerificationResult, VerificationStatus
from app.contracts.workflow import (
    WorkflowDefinition,
    WorkflowExecutionEvent,
    WorkflowStepDefinition,
    WorkflowStepStatus,
)

__all__ = [
    "AgentAdapter",
    "AgentDescriptor",
    "AgentExecutionRequest",
    "AgentExecutionResult",
    "AgentUsage",
    "RepositoryMetadata",
    "BenchmarkDefinition",
    "BenchmarkResult",
    "BenchmarkTask",
    "AgentCapability",
    "AgentExecutionStatus",
    "AgentStatus",
    "BenchmarkEvaluatorType",
    "RuntimeKind",
    "RETRYABLE_FAILURE_CATEGORIES",
    "FailureCategory",
    "classify_legacy_error_type",
    "Confidence",
    "CounterfactualCondition",
    "DecisionTrace",
    "DecisionType",
    "EvidenceItem",
    "ExclusionReason",
    "RoutingExplanation",
    "ScoreContribution",
    "KnowledgeDocument",
    "KnowledgeSearchResult",
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
    "AgentPassport",
    "AgentPassportMetricBucket",
    "ExpectedOutcome",
    "PlanningRequest",
    "TaskSpec",
    "WorkflowPlan",
    "RoutingCandidateScore",
    "RoutingConstraints",
    "RoutingDecision",
    "RoutingRequest",
    "QualityContractValidationError",
    "QualityEvidence",
    "QualityExecutionContext",
    "QualityGateResult",
    "QualityGateSpec",
    "QualityGateStatus",
    "QualityGateType",
    "QualityProfile",
    "QualityRepairPacket",
    "QualityRun",
    "QualityVerdict",
    "QualityVerdictStatus",
    "SkillAssignment",
    "SkillCategory",
    "SkillContract",
    "SkillContractValidationError",
    "SkillExecutionTrace",
    "SkillStatus",
    "VerificationEvidence",
    "VerificationResult",
    "VerificationStatus",
    "WorkflowDefinition",
    "WorkflowExecutionEvent",
    "WorkflowStepDefinition",
    "WorkflowStepStatus",
]
