"""Stage 9C Skill Foundry REST API Endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import (
    get_candidate_skill_foundry,
    get_skill_evidence_repo,
    get_skill_lifecycle_manager,
    get_skill_registry,
)
from app.contracts.enums import AgentCapability
from app.contracts.skills import SkillCategory, SkillContract, SkillStatus
from app.engine.skills.errors import SkillNotFoundError
from app.engine.skills.evidence import (
    SkillEvidenceRepository,
)
from app.engine.skills.foundry import CandidateSkillFoundry
from app.engine.skills.lifecycle import SkillLifecycleManager
from app.engine.skills.registry import SkillRegistry
from app.engine.skills.retriever import SkillRetriever
from app.engine.skills.vault import ObsidianSkillVault

router = APIRouter(prefix="/skills", tags=["skills"])


class SkillResponse(BaseModel):
    skill_id: str
    version: str
    name: str
    description: str
    category: str
    task_types: list[str]
    capabilities: list[str]
    languages: list[str]
    frameworks: list[str]
    preconditions: list[str]
    contraindications: list[str]
    procedure: str
    verification_contract: dict[str, Any]
    source: str
    status: str
    provenance: dict[str, Any]

    @classmethod
    def from_contract(cls, s: SkillContract) -> "SkillResponse":
        cat_val = s.category.value if isinstance(s.category, SkillCategory) else str(s.category)
        return cls(
            skill_id=s.skill_id,
            version=s.version,
            name=s.name,
            description=s.description,
            category=cat_val,
            task_types=list(s.task_types),
            capabilities=[c.value for c in s.capabilities],
            languages=list(s.languages),
            frameworks=list(s.frameworks),
            preconditions=list(s.preconditions),
            contraindications=list(s.contraindications),
            procedure=s.procedure,
            verification_contract=s.verification_contract,
            source=s.source,
            status=s.status.value,
            provenance=s.provenance,
        )


class SkillSearchRequest(BaseModel):
    task_type: str
    objective: str = ""
    title: str = ""
    required_capabilities: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    limit: int = 5


class SkillSearchMatchResponse(BaseModel):
    skill: SkillResponse
    total_score: float
    semantic_relevance: float
    capability_match: float
    task_type_match: float
    project_relevance: float
    verified_utility: float
    explanation: str


class VaultIngestRequest(BaseModel):
    vault_path: str


class VaultIngestResponse(BaseModel):
    ingested_count: int
    errors: list[list[str]]


class ProposalResponse(BaseModel):
    proposal_id: str
    skill_id: str
    name: str
    description: str
    category: str
    task_types: list[str]
    capabilities: list[str]
    languages: list[str]
    frameworks: list[str]
    supporting_evidence_count: int
    origin_execution_ids: list[str]


@router.get("", response_model=list[SkillResponse])
def list_skills(
    status_filter: SkillStatus | None = Query(None, alias="status"),  # noqa: B008
    category: str | None = None,
    task_type: str | None = None,
    capability: AgentCapability | None = None,
    language: str | None = None,
    framework: str | None = None,
    latest_only: bool = True,
    registry: SkillRegistry = Depends(get_skill_registry),  # noqa: B008
) -> list[SkillResponse]:
    """List skills in the registry with optional filters."""
    skills = registry.list_skills(
        status=status_filter,
        category=category,
        task_type=task_type,
        capability=capability,
        language=language,
        framework=framework,
        latest_only=latest_only,
    )
    return [SkillResponse.from_contract(s) for s in skills]


@router.get("/candidates", response_model=list[ProposalResponse])
def list_candidates(
    foundry: CandidateSkillFoundry = Depends(get_candidate_skill_foundry),  # noqa: B008
) -> list[ProposalResponse]:
    """List pending candidate skill proposals."""
    proposals = foundry.list_proposals()
    return [
        ProposalResponse(
            proposal_id=p.proposal_id,
            skill_id=p.skill_id,
            name=p.name,
            description=p.description,
            category=(
                p.category.value if isinstance(p.category, SkillCategory) else str(p.category)
            ),
            task_types=list(p.task_types),
            capabilities=[c.value for c in p.capabilities],
            languages=list(p.languages),
            frameworks=list(p.frameworks),
            supporting_evidence_count=p.supporting_evidence_count,
            origin_execution_ids=list(p.origin_execution_ids),
        )
        for p in proposals
    ]


@router.post("/candidates/{proposal_id}/approve", response_model=SkillResponse)
def approve_candidate(
    proposal_id: str,
    foundry: CandidateSkillFoundry = Depends(get_candidate_skill_foundry),  # noqa: B008
) -> SkillResponse:
    """Approve a candidate proposal into the registry."""
    try:
        skill = foundry.approve_proposal(proposal_id)
        return SkillResponse.from_contract(skill)
    except KeyError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.post("/candidates/{proposal_id}/reject")
def reject_candidate(
    proposal_id: str,
    reason: str = Query("Rejected by user"),  # noqa: B008
    foundry: CandidateSkillFoundry = Depends(get_candidate_skill_foundry),  # noqa: B008
) -> dict[str, str]:
    """Reject a candidate proposal."""
    try:
        foundry.reject_proposal(proposal_id, reason=reason)
        return {"status": "rejected", "proposal_id": proposal_id, "reason": reason}
    except KeyError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.post("/search", response_model=list[SkillSearchMatchResponse])
def search_skills(
    req: SkillSearchRequest,
    registry: SkillRegistry = Depends(get_skill_registry),  # noqa: B008
    evidence_repo: SkillEvidenceRepository = Depends(get_skill_evidence_repo),  # noqa: B008
) -> list[SkillSearchMatchResponse]:
    """Search and rank skills matching a task."""
    import contextlib

    from app.contracts.planning import TaskSpec

    caps = []
    for c in req.required_capabilities:
        with contextlib.suppress(ValueError):
            caps.append(AgentCapability(c))

    dummy_task = TaskSpec(
        key="search-task",
        name=req.title or req.task_type,
        task_type=req.task_type,
        required_capabilities=caps,
        input_payload={"objective": req.objective},
    )

    retriever = SkillRetriever(registry=registry, evidence_repo=evidence_repo)
    matches = retriever.retrieve_skills_for_task(
        task=dummy_task,
        workspace_context={"languages": req.languages, "frameworks": req.frameworks},
        limit=req.limit,
    )

    return [
        SkillSearchMatchResponse(
            skill=SkillResponse.from_contract(m.skill),
            total_score=m.total_score,
            semantic_relevance=m.semantic_relevance,
            capability_match=m.capability_match,
            task_type_match=m.task_type_match,
            project_relevance=m.project_relevance,
            verified_utility=m.verified_utility,
            explanation=m.explanation,
        )
        for m in matches
    ]


@router.post("/vault/ingest", response_model=VaultIngestResponse)
def ingest_vault(
    req: VaultIngestRequest,
    registry: SkillRegistry = Depends(get_skill_registry),  # noqa: B008
) -> VaultIngestResponse:
    """Ingest skills from an Obsidian vault on disk."""
    try:
        vault = ObsidianSkillVault(vault_root=req.vault_path)
        count, errors = registry.ingest_vault(vault)
        return VaultIngestResponse(ingested_count=count, errors=[[k, v] for k, v in errors])
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to ingest vault: {e}"
        ) from e


@router.get("/{skill_id}", response_model=SkillResponse)
def get_skill(
    skill_id: str,
    version: str | None = None,
    registry: SkillRegistry = Depends(get_skill_registry),  # noqa: B008
) -> SkillResponse:
    """Get a specific skill by ID and optional version."""
    try:
        skill = registry.get_skill(skill_id, version)
        return SkillResponse.from_contract(skill)
    except SkillNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.get("/{skill_id}/versions", response_model=list[SkillResponse])
def get_skill_versions(
    skill_id: str,
    registry: SkillRegistry = Depends(get_skill_registry),  # noqa: B008
) -> list[SkillResponse]:
    """Get all versions of a skill."""
    versions = registry.get_all_versions(skill_id)
    if not versions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Skill '{skill_id}' not found"
        )
    return [SkillResponse.from_contract(s) for s in versions]


@router.get("/{skill_id}/evidence")
def get_skill_evidence(
    skill_id: str,
    version: str | None = None,
    evidence_repo: SkillEvidenceRepository = Depends(get_skill_evidence_repo),  # noqa: B008
) -> dict[str, Any]:
    """Get metrics and raw evidence records for a skill."""
    metrics = evidence_repo.get_metrics_for_skill(skill_id, version)
    records = evidence_repo.get_evidence_for_skill(skill_id, version)
    return {
        "metrics": {
            "skill_id": metrics.skill_id,
            "skill_version": metrics.skill_version,
            "total_samples": metrics.total_samples,
            "verified_successes": metrics.verified_successes,
            "verified_failures": metrics.verified_failures,
            "raw_success_rate": metrics.raw_success_rate,
            "smoothed_reliability": metrics.smoothed_reliability(),
            "mean_latency_ms": metrics.mean_latency_ms,
            "recovery_count": metrics.recovery_count,
        },
        "records_count": len(records),
    }


@router.post("/{skill_id}/deprecate", response_model=SkillResponse)
def deprecate_skill(
    skill_id: str,
    version: str | None = None,
    lifecycle_mgr: SkillLifecycleManager = Depends(get_skill_lifecycle_manager),  # noqa: B008
) -> SkillResponse:
    """Explicitly deprecate a skill."""
    try:
        updated = lifecycle_mgr.human_deprecate_skill(skill_id, version)
        return SkillResponse.from_contract(updated)
    except SkillNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


__all__ = ["router"]

