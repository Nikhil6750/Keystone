"""FastAPI REST routes for Stage 9E Engineering Intelligence Graph queries.

Read-only by design (see module docstring in
`app.engine.intelligence.query_service`): no route here can mark a failed
attempt/gate as passed, mutate a historical node/edge/attribution, or
otherwise forge a reliability or failure observation -- every response is a
deterministic aggregation over already-persisted evidence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from app.contracts.intelligence import FailureAttributionCategory
from app.engine.intelligence.graph_repository import (
    IntelligenceGraphRepository,
    SqlAlchemyIntelligenceGraphRepository,
)
from app.engine.intelligence.query_service import EngineeringIntelligenceQueryService

router = APIRouter(prefix="/intelligence", tags=["Engineering Intelligence"])

# Module-level singleton so `since: datetime | None = _SINCE_QUERY` never
# calls `Query(...)` inline in a function signature's default value.
_SINCE_QUERY = Query(default=None)


def _get_query_service(request: Request) -> EngineeringIntelligenceQueryService:
    """Dependency provider for `EngineeringIntelligenceQueryService`."""
    if hasattr(request.app.state, "intelligence_query_service"):
        return request.app.state.intelligence_query_service  # type: ignore[no-any-return]
    from app.database.session import SessionLocal

    repo: IntelligenceGraphRepository = SqlAlchemyIntelligenceGraphRepository(
        session_factory=SessionLocal
    )
    return EngineeringIntelligenceQueryService(repo)


# --- Response schemas ---------------------------------------------------------


class IntelligenceNodeSchema(BaseModel):
    node_id: str
    node_type: str
    canonical_id: str
    label: str
    workflow_id: str | None = None
    agent_type: str | None = None
    task_type: str | None = None
    skill_id: str | None = None
    skill_version: str | None = None
    status: str | None = None
    metadata: dict[str, Any] = {}
    created_at: str


class IntelligenceEdgeSchema(BaseModel):
    edge_id: str
    edge_type: str
    source_node_id: str
    target_node_id: str
    created_at: str


class NodeRelationshipsSchema(BaseModel):
    node: IntelligenceNodeSchema
    outgoing: list[IntelligenceEdgeSchema]
    incoming: list[IntelligenceEdgeSchema]


class TaskReliabilitySchema(BaseModel):
    task_type: str | None
    attempt_count: int
    success_count: int
    failure_count: int
    recovery_count: int
    quality_rejection_count: int
    success_rate: float | None
    sample_size_is_low: bool


class AgentReliabilitySchema(BaseModel):
    agent_type: str
    task_type: str | None
    observed_executions: int
    successful_executions: int
    failed_executions: int
    recovery_count: int
    quality_verified_successes: int
    success_rate: float | None
    sample_size_is_low: bool


class SkillReliabilitySchema(BaseModel):
    skill_id: str
    skill_version: str | None
    task_type: str | None
    uses: int
    successful_uses: int
    failed_uses: int
    quality_verified_uses: int
    success_rate: float | None
    sample_size_is_low: bool


class QualityGateIntelligenceSchema(BaseModel):
    task_type: str | None
    agent_type: str | None
    skill_id: str | None
    total_gate_results: int
    passed_count: int
    failed_count: int
    error_count: int
    skipped_count: int
    most_frequent_failed_gate_types: list[list[Any]]
    sample_size_is_low: bool


class FailureAttributionSchema(BaseModel):
    attribution_id: str
    attempt_node_id: str
    category: str
    is_known: bool
    explanation: str
    evidence_ids: list[str]
    workflow_id: str | None
    agent_type: str | None
    task_type: str | None
    skill_id: str | None
    created_at: str


def _node_schema(node: Any) -> IntelligenceNodeSchema:
    return IntelligenceNodeSchema(
        node_id=node.node_id,
        node_type=node.node_type.value,
        canonical_id=node.canonical_id,
        label=node.label,
        workflow_id=node.workflow_id,
        agent_type=node.agent_type,
        task_type=node.task_type,
        skill_id=node.skill_id,
        skill_version=node.skill_version,
        status=node.status,
        metadata=dict(node.metadata),
        created_at=node.created_at.isoformat(),
    )


def _edge_schema(edge: Any) -> IntelligenceEdgeSchema:
    return IntelligenceEdgeSchema(
        edge_id=edge.edge_id,
        edge_type=edge.edge_type.value,
        source_node_id=edge.source_node_id,
        target_node_id=edge.target_node_id,
        created_at=edge.created_at.isoformat(),
    )


def _attribution_schema(attribution: Any) -> FailureAttributionSchema:
    return FailureAttributionSchema(
        attribution_id=attribution.attribution_id,
        attempt_node_id=attribution.attempt_node_id,
        category=attribution.category.value,
        is_known=attribution.is_known,
        explanation=attribution.explanation,
        evidence_ids=list(attribution.evidence_ids),
        workflow_id=attribution.workflow_id,
        agent_type=attribution.agent_type,
        task_type=attribution.task_type,
        skill_id=attribution.skill_id,
        created_at=attribution.created_at.isoformat(),
    )


# --- Endpoints ------------------------------------------------------------------


@router.get("/nodes/{node_id}/relationships", response_model=NodeRelationshipsSchema)
def get_node_relationships(
    node_id: str,
    svc: Annotated[EngineeringIntelligenceQueryService, Depends(_get_query_service)],
) -> NodeRelationshipsSchema:
    """Retrieve one graph node and every edge attached to it -- the
    provenance trail back to the underlying evidence."""
    node = svc.get_node(node_id)
    if node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Intelligence node '{node_id}' not found.",
        )
    outgoing, incoming = svc.get_relationships(node_id)
    return NodeRelationshipsSchema(
        node=_node_schema(node),
        outgoing=[_edge_schema(e) for e in outgoing],
        incoming=[_edge_schema(e) for e in incoming],
    )


@router.get("/tasks/reliability", response_model=TaskReliabilitySchema)
def get_task_reliability(
    svc: Annotated[EngineeringIntelligenceQueryService, Depends(_get_query_service)],
    task_type: str | None = Query(default=None),
    since: datetime | None = _SINCE_QUERY,
) -> TaskReliabilitySchema:
    """Deterministic reliability signal for one task type (or all task
    types when `task_type` is omitted)."""
    obs = svc.get_task_reliability(task_type=task_type, since=since)
    return TaskReliabilitySchema(
        task_type=obs.task_type,
        attempt_count=obs.attempt_count,
        success_count=obs.success_count,
        failure_count=obs.failure_count,
        recovery_count=obs.recovery_count,
        quality_rejection_count=obs.quality_rejection_count,
        success_rate=obs.success_rate,
        sample_size_is_low=obs.sample_size_is_low,
    )


@router.get("/agents/{agent_type}/reliability", response_model=AgentReliabilitySchema)
def get_agent_reliability(
    agent_type: str,
    svc: Annotated[EngineeringIntelligenceQueryService, Depends(_get_query_service)],
    task_type: str | None = Query(default=None),
    since: datetime | None = _SINCE_QUERY,
) -> AgentReliabilitySchema:
    """Deterministic reliability signal for one agent (provider-neutral
    runtime identifier), optionally scoped to a task type."""
    obs = svc.get_agent_reliability(agent_type, task_type=task_type, since=since)
    return AgentReliabilitySchema(
        agent_type=obs.agent_type,
        task_type=obs.task_type,
        observed_executions=obs.observed_executions,
        successful_executions=obs.successful_executions,
        failed_executions=obs.failed_executions,
        recovery_count=obs.recovery_count,
        quality_verified_successes=obs.quality_verified_successes,
        success_rate=obs.success_rate,
        sample_size_is_low=obs.sample_size_is_low,
    )


@router.get("/skills/{skill_id}/reliability", response_model=SkillReliabilitySchema)
def get_skill_reliability(
    skill_id: str,
    svc: Annotated[EngineeringIntelligenceQueryService, Depends(_get_query_service)],
    skill_version: str | None = Query(default=None),
    task_type: str | None = Query(default=None),
    since: datetime | None = _SINCE_QUERY,
) -> SkillReliabilitySchema:
    """Deterministic reliability signal for one skill (optionally scoped to
    a version and/or task type)."""
    obs = svc.get_skill_reliability(
        skill_id, skill_version, task_type=task_type, since=since
    )
    return SkillReliabilitySchema(
        skill_id=obs.skill_id,
        skill_version=obs.skill_version,
        task_type=obs.task_type,
        uses=obs.uses,
        successful_uses=obs.successful_uses,
        failed_uses=obs.failed_uses,
        quality_verified_uses=obs.quality_verified_uses,
        success_rate=obs.success_rate,
        sample_size_is_low=obs.sample_size_is_low,
    )


@router.get("/quality/gates", response_model=QualityGateIntelligenceSchema)
def get_quality_gate_intelligence(
    svc: Annotated[EngineeringIntelligenceQueryService, Depends(_get_query_service)],
    task_type: str | None = Query(default=None),
    agent_type: str | None = Query(default=None),
    skill_id: str | None = Query(default=None),
    since: datetime | None = _SINCE_QUERY,
) -> QualityGateIntelligenceSchema:
    """Aggregate Stage 9D quality gate outcomes reachable through the
    graph, optionally scoped to task/agent/skill context."""
    obs = svc.get_quality_gate_intelligence(
        task_type=task_type, agent_type=agent_type, skill_id=skill_id, since=since
    )
    return QualityGateIntelligenceSchema(
        task_type=obs.task_type,
        agent_type=obs.agent_type,
        skill_id=obs.skill_id,
        total_gate_results=obs.total_gate_results,
        passed_count=obs.passed_count,
        failed_count=obs.failed_count,
        error_count=obs.error_count,
        skipped_count=obs.skipped_count,
        most_frequent_failed_gate_types=[list(t) for t in obs.most_frequent_failed_gate_types],
        sample_size_is_low=obs.sample_size_is_low,
    )


@router.get("/failures", response_model=list[FailureAttributionSchema])
def get_failure_history(
    svc: Annotated[EngineeringIntelligenceQueryService, Depends(_get_query_service)],
    task_type: str | None = Query(default=None),
    agent_type: str | None = Query(default=None),
    skill_id: str | None = Query(default=None),
    category: str | None = Query(default=None),
    since: datetime | None = _SINCE_QUERY,
    limit: int = Query(default=50, ge=1, le=500),
) -> list[FailureAttributionSchema]:
    """Evidence-based failure attribution history, optionally filtered by
    task/agent/skill context and/or category."""
    category_enum: FailureAttributionCategory | None = None
    if category is not None:
        try:
            category_enum = FailureAttributionCategory(category)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown failure attribution category: '{category}'.",
            ) from exc

    attributions = svc.get_failure_history(
        task_type=task_type,
        agent_type=agent_type,
        skill_id=skill_id,
        category=category_enum,
        since=since,
        limit=limit,
    )
    return [_attribution_schema(a) for a in attributions]


__all__ = ["router"]
