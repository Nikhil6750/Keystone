"""Workflow REST API routes."""

import logging

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_workflow_engine
from app.database.session import get_db
from app.engine.exceptions import WorkflowNotFoundError
from app.engine.workflow_engine import WorkflowEngine
from app.models.workflow import Workflow
from app.schemas.workflow import WorkflowCreate, WorkflowListResponse, WorkflowRead
from app.services import workflow_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post("", response_model=WorkflowRead, status_code=status.HTTP_201_CREATED)
def create_workflow(data: WorkflowCreate, db: Session = Depends(get_db)) -> Workflow:  # noqa: B008
    """Validate and persist a new workflow with its ordered steps. Does not execute it."""
    workflow = workflow_service.create_workflow(db, data)
    logger.info("workflow_created workflow_id=%s step_count=%s", workflow.id, len(workflow.steps))
    return workflow


@router.get("/{workflow_id}", response_model=WorkflowRead)
def get_workflow(workflow_id: str, db: Session = Depends(get_db)) -> Workflow:  # noqa: B008
    """Retrieve a workflow with its ordered steps and attempt history."""
    workflow = workflow_service.get_workflow(db, workflow_id)
    if workflow is None:
        raise WorkflowNotFoundError(workflow_id)
    return workflow


@router.get("", response_model=WorkflowListResponse)
def list_workflows(
    limit: int = Query(default=50, ge=1, le=100),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> WorkflowListResponse:
    """List workflows newest-first, bounded by `limit` (default 50, max 100)."""
    items = workflow_service.list_workflows(db, limit=limit)
    return WorkflowListResponse.model_validate({"items": items, "count": len(items)})


@router.post("/{workflow_id}/execute", response_model=WorkflowRead)
def execute_workflow(
    workflow_id: str,
    engine: WorkflowEngine = Depends(get_workflow_engine),  # noqa: B008
) -> Workflow:
    """Synchronously execute a `PENDING` workflow's steps in position order.

    Returns the updated workflow whether it succeeded or a step failed with an
    expected error; raises for a missing workflow (404), an invalid starting
    state (409), or a missing executor registration (503).
    """
    return engine.execute_workflow(workflow_id)
