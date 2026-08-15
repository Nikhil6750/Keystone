"""FastAPI REST routes for Stage 9D Software Quality Factory inspection and profiles."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.contracts.quality import (
    QualityGateSpec,
    QualityProfile,
)
from app.database.session import SessionLocal
from app.engine.quality.repository import (
    QualityRepository,
    SqlAlchemyQualityRepository,
)

router = APIRouter(prefix="/quality", tags=["Quality Factory"])


def _get_quality_repo(request: Request) -> QualityRepository:
    """Dependency provider for QualityRepository."""
    if hasattr(request.app.state, "quality_repository"):
        return request.app.state.quality_repository  # type: ignore[no-any-return]
    # Default to SqlAlchemy repository
    return SqlAlchemyQualityRepository(session_factory=SessionLocal)


# --- Request / Response Schemas ----------------------------------------------


class QualityGateSpecSchema(BaseModel):
    gate_id: str
    gate_type: str
    name: str
    required: bool = True
    timeout_seconds: float = 30.0
    applicable_scope: str = "workspace"
    configuration: dict[str, Any] = Field(default_factory=dict)
    order: int = 0


class QualityProfileCreateSchema(BaseModel):
    profile_id: str
    name: str
    description: str = ""
    target_languages: list[str] = Field(default_factory=list)
    target_frameworks: list[str] = Field(default_factory=list)
    gates: list[QualityGateSpecSchema] = Field(default_factory=list)
    is_default: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class QualityEvidenceSchema(BaseModel):
    summary: str
    exit_code: int | None = None
    diagnostics: list[str] = Field(default_factory=list)
    artifact_references: list[str] = Field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)


class QualityGateResultSchema(BaseModel):
    gate_id: str
    gate_type: str
    name: str
    status: str
    required: bool
    evidence: QualityEvidenceSchema
    execution_time_ms: float
    failure_reason: str | None = None
    skip_reason: str | None = None
    timestamp: str


class QualityVerdictSchema(BaseModel):
    verdict_id: str
    status: str
    passed: bool
    total_gates: int
    passed_gates: int
    failed_gates: int
    skipped_gates: int
    error_gates: int
    summary_explanation: str
    created_at: str


class QualityRunSchema(BaseModel):
    run_id: str
    execution_id: str
    workflow_id: str | None = None
    task_id: str | None = None
    attempt_number: int
    agent_id: str | None = None
    skill_id: str | None = None
    skill_version: str | None = None
    profile_id: str | None = None
    status: str
    passed: bool
    verdict: QualityVerdictSchema | None = None
    created_at: str
    completed_at: str | None = None


# --- Endpoints ---------------------------------------------------------------


@router.get("/runs/{run_id}", response_model=QualityRunSchema)
def get_quality_run(
    run_id: str,
    repo: Annotated[QualityRepository, Depends(_get_quality_repo)],
) -> QualityRunSchema:
    """Retrieve full details of a specific quality run."""
    run = repo.get_run(run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Quality run '{run_id}' not found.",
        )

    verdict_schema = None
    if run.verdict:
        verdict_schema = QualityVerdictSchema(
            verdict_id=run.verdict.verdict_id,
            status=run.verdict.status.value,
            passed=run.verdict.passed,
            total_gates=run.verdict.total_gates,
            passed_gates=run.verdict.passed_gates,
            failed_gates=run.verdict.failed_gates,
            skipped_gates=run.verdict.skipped_gates,
            error_gates=run.verdict.error_gates,
            summary_explanation=run.verdict.summary_explanation,
            created_at=run.verdict.created_at.isoformat(),
        )

    return QualityRunSchema(
        run_id=run.run_id,
        execution_id=run.execution_id,
        workflow_id=run.workflow_id,
        task_id=run.task_id,
        attempt_number=run.attempt_number,
        agent_id=run.agent_id,
        skill_id=run.skill_id,
        skill_version=run.skill_version,
        profile_id=run.profile_id,
        status=run.verdict.status.value if run.verdict else "UNKNOWN",
        passed=run.verdict.passed if run.verdict else False,
        verdict=verdict_schema,
        created_at=run.created_at.isoformat(),
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
    )


@router.get("/runs/{run_id}/gates", response_model=list[QualityGateResultSchema])
def get_quality_run_gates(
    run_id: str,
    repo: Annotated[QualityRepository, Depends(_get_quality_repo)],
) -> list[QualityGateResultSchema]:
    """Retrieve all individual quality gate results and evidence for a run."""
    run = repo.get_run(run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Quality run '{run_id}' not found.",
        )

    gates = repo.get_gate_results_for_run(run_id)
    return [
        QualityGateResultSchema(
            gate_id=g.gate_id,
            gate_type=g.gate_type.value if hasattr(g.gate_type, "value") else str(g.gate_type),
            name=g.name,
            status=g.status.value if hasattr(g.status, "value") else str(g.status),
            required=g.required,
            evidence=QualityEvidenceSchema(
                summary=g.evidence.summary if g.evidence else "",
                exit_code=g.evidence.exit_code if g.evidence else None,
                diagnostics=list(g.evidence.diagnostics) if g.evidence else [],
                artifact_references=list(g.evidence.artifact_references) if g.evidence else [],
                stdout=g.evidence.stdout if g.evidence else "",
                stderr=g.evidence.stderr if g.evidence else "",
                metrics=dict(g.evidence.metrics) if g.evidence else {},
            ),
            execution_time_ms=g.execution_time_ms,
            failure_reason=g.failure_reason,
            skip_reason=g.skip_reason,
            timestamp=g.timestamp.isoformat(),
        )
        for g in gates
    ]


@router.get("/runs/{run_id}/verdict", response_model=QualityVerdictSchema)
def get_quality_run_verdict(
    run_id: str,
    repo: Annotated[QualityRepository, Depends(_get_quality_repo)],
) -> QualityVerdictSchema:
    """Retrieve the authoritative final quality verdict for a run."""
    run = repo.get_run(run_id)
    if not run or not run.verdict:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Quality verdict for run '{run_id}' not found.",
        )
    v = run.verdict
    return QualityVerdictSchema(
        verdict_id=v.verdict_id,
        status=v.status.value,
        passed=v.passed,
        total_gates=v.total_gates,
        passed_gates=v.passed_gates,
        failed_gates=v.failed_gates,
        skipped_gates=v.skipped_gates,
        error_gates=v.error_gates,
        summary_explanation=v.summary_explanation,
        created_at=v.created_at.isoformat(),
    )


@router.get("/history", response_model=list[QualityRunSchema])
def get_quality_history(
    execution_id: str | None = Query(default=None),
    task_id: str | None = Query(default=None),
    workflow_id: str | None = Query(default=None),
    repo: Annotated[QualityRepository, Depends(_get_quality_repo)] = None,  # type: ignore[assignment]
) -> list[QualityRunSchema]:
    """Retrieve quality run history filtered by execution_id, task_id, or workflow_id."""
    runs: list[Any] = []
    if execution_id:
        runs = repo.get_runs_by_execution(execution_id)
    elif task_id:
        runs = repo.get_runs_by_task(task_id)
    elif workflow_id:
        runs = repo.get_runs_by_workflow(workflow_id)
    else:
        # Require at least one filter
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "At least one of execution_id, task_id, or workflow_id "
                "query parameter is required."
            ),
        )

    results: list[QualityRunSchema] = []
    for run in runs:
        verdict_schema = None
        if run.verdict:
            verdict_schema = QualityVerdictSchema(
                verdict_id=run.verdict.verdict_id,
                status=run.verdict.status.value,
                passed=run.verdict.passed,
                total_gates=run.verdict.total_gates,
                passed_gates=run.verdict.passed_gates,
                failed_gates=run.verdict.failed_gates,
                skipped_gates=run.verdict.skipped_gates,
                error_gates=run.verdict.error_gates,
                summary_explanation=run.verdict.summary_explanation,
                created_at=run.verdict.created_at.isoformat(),
            )

        results.append(
            QualityRunSchema(
                run_id=run.run_id,
                execution_id=run.execution_id,
                workflow_id=run.workflow_id,
                task_id=run.task_id,
                attempt_number=run.attempt_number,
                agent_id=run.agent_id,
                skill_id=run.skill_id,
                skill_version=run.skill_version,
                profile_id=run.profile_id,
                status=run.verdict.status.value if run.verdict else "UNKNOWN",
                passed=run.verdict.passed if run.verdict else False,
                verdict=verdict_schema,
                created_at=run.created_at.isoformat(),
                completed_at=run.completed_at.isoformat() if run.completed_at else None,
            )
        )
    return results


@router.get("/profiles", response_model=list[QualityProfileCreateSchema])
def list_quality_profiles(
    repo: Annotated[QualityRepository, Depends(_get_quality_repo)],
) -> list[QualityProfileCreateSchema]:
    """List all registered quality profiles."""
    profiles = repo.list_profiles()
    return [
        QualityProfileCreateSchema(
            profile_id=p.profile_id,
            name=p.name,
            description=p.description,
            target_languages=list(p.target_languages),
            target_frameworks=list(p.target_frameworks),
            gates=[
                QualityGateSpecSchema(
                    gate_id=g.gate_id,
                    gate_type=g.gate_type.value
                    if hasattr(g.gate_type, "value")
                    else str(g.gate_type),
                    name=g.name,
                    required=g.required,
                    timeout_seconds=g.timeout_seconds,
                    applicable_scope=g.applicable_scope,
                    configuration=g.configuration,
                    order=g.order,
                )
                for g in p.gates
            ],
            is_default=p.is_default,
            metadata=p.metadata,
        )
        for p in profiles
    ]


@router.get("/profiles/{profile_id}", response_model=QualityProfileCreateSchema)
def get_quality_profile(
    profile_id: str,
    repo: Annotated[QualityRepository, Depends(_get_quality_repo)],
) -> QualityProfileCreateSchema:
    """Retrieve a specific quality profile by ID."""
    p = repo.get_profile(profile_id)
    if not p:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Quality profile '{profile_id}' not found.",
        )
    return QualityProfileCreateSchema(
        profile_id=p.profile_id,
        name=p.name,
        description=p.description,
        target_languages=list(p.target_languages),
        target_frameworks=list(p.target_frameworks),
        gates=[
            QualityGateSpecSchema(
                gate_id=g.gate_id,
                gate_type=g.gate_type.value if hasattr(g.gate_type, "value") else str(g.gate_type),
                name=g.name,
                required=g.required,
                timeout_seconds=g.timeout_seconds,
                applicable_scope=g.applicable_scope,
                configuration=g.configuration,
                order=g.order,
            )
            for g in p.gates
        ],
        is_default=p.is_default,
        metadata=p.metadata,
    )


@router.post(
    "/profiles", response_model=QualityProfileCreateSchema, status_code=status.HTTP_201_CREATED
)
def register_quality_profile(
    payload: QualityProfileCreateSchema,
    repo: Annotated[QualityRepository, Depends(_get_quality_repo)],
) -> QualityProfileCreateSchema:
    """Register or update a quality profile."""
    gate_specs = [
        QualityGateSpec(
            gate_id=g.gate_id,
            gate_type=g.gate_type,
            name=g.name,
            required=g.required,
            timeout_seconds=g.timeout_seconds,
            applicable_scope=g.applicable_scope,
            configuration=g.configuration,
            order=g.order,
        )
        for g in payload.gates
    ]
    profile = QualityProfile(
        profile_id=payload.profile_id,
        name=payload.name,
        description=payload.description,
        target_languages=tuple(payload.target_languages),
        target_frameworks=tuple(payload.target_frameworks),
        gates=tuple(gate_specs),
        is_default=payload.is_default,
        metadata=payload.metadata,
    )
    repo.save_profile(profile)
    return payload


__all__ = ["router"]
