"""Audit-event, chain-verification, and provenance API routes."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.audit import service as audit_service
from app.audit import verification as audit_verification
from app.database.session import get_db
from app.engine.exceptions import WorkflowNotFoundError
from app.schemas.audit import AuditEventListResponse, ChainVerificationRead, ProvenanceRead
from app.services import workflow_service

router = APIRouter(prefix="/workflows", tags=["audit"])


def _ensure_workflow_exists(db: Session, workflow_id: str) -> None:
    if workflow_service.get_workflow(db, workflow_id) is None:
        raise WorkflowNotFoundError(workflow_id)


@router.get("/{workflow_id}/audit-events", response_model=AuditEventListResponse)
def get_audit_events(
    workflow_id: str,
    limit: int = Query(default=100, ge=1, le=500),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> AuditEventListResponse:
    """List a workflow's audit events in sequence order, bounded by `limit` (default 100)."""
    _ensure_workflow_exists(db, workflow_id)
    items = audit_service.list_events(db, workflow_id, limit=limit)
    return AuditEventListResponse.model_validate({"items": items, "count": len(items)})


@router.get("/{workflow_id}/audit-chain/verify", response_model=ChainVerificationRead)
def verify_audit_chain(
    workflow_id: str,
    db: Session = Depends(get_db),  # noqa: B008
) -> ChainVerificationRead:
    """Verify a workflow's audit chain.

    Always returns `200 OK` — an invalid chain (`valid: false`) is a
    verification *result*, not an HTTP transport failure.
    """
    _ensure_workflow_exists(db, workflow_id)
    result = audit_verification.verify_chain(db, workflow_id)
    return ChainVerificationRead.model_validate(result)


@router.get("/{workflow_id}/provenance", response_model=ProvenanceRead)
def get_provenance(
    workflow_id: str,
    db: Session = Depends(get_db),  # noqa: B008
) -> ProvenanceRead:
    """Return an ordered provenance trace for a workflow, including chain validity."""
    _ensure_workflow_exists(db, workflow_id)
    provenance = audit_verification.build_provenance(db, workflow_id)
    return ProvenanceRead.model_validate(provenance)
