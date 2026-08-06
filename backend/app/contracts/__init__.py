"""Canonical, provider-neutral domain contracts shared across the engine, API,
CLI and extension clients.

This package is additive: it does not replace `app.schemas` (the live API
request/response contract) or `app.models.enums` (the live persisted
workflow/step status enums). Those remain the source of truth for behavior
that already ships. `app.contracts` defines the vNext shapes — the
provider-neutral `AgentAdapter` protocol, the DAG-aware workflow definition,
routing, agent-passport, knowledge and benchmark contracts — that later
stages incrementally wire into persistence, the engine and the API layer.

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
)
from app.contracts.errors import (
    RETRYABLE_FAILURE_CATEGORIES,
    FailureCategory,
    classify_legacy_error_type,
)
from app.contracts.knowledge import KnowledgeDocument, KnowledgeSearchResult
from app.contracts.passports import AgentPassport, AgentPassportMetricBucket
from app.contracts.routing import RoutingCandidateScore, RoutingDecision, RoutingRequest
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
    "RETRYABLE_FAILURE_CATEGORIES",
    "FailureCategory",
    "classify_legacy_error_type",
    "KnowledgeDocument",
    "KnowledgeSearchResult",
    "AgentPassport",
    "AgentPassportMetricBucket",
    "RoutingCandidateScore",
    "RoutingDecision",
    "RoutingRequest",
    "WorkflowDefinition",
    "WorkflowExecutionEvent",
    "WorkflowStepDefinition",
    "WorkflowStepStatus",
]
