"""Workflow persistence and state-transition operations."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.engine.state_machine import InvalidStateTransition
from app.engine.state_machine import transition_step as apply_step_transition
from app.engine.state_machine import transition_workflow as apply_workflow_transition
from app.models.compensation_attempt import CompensationAttempt
from app.models.enums import AttemptStatus, CompensationAttemptStatus, StepStatus, WorkflowStatus
from app.models.step_attempt import StepAttempt
from app.models.workflow import Workflow
from app.models.workflow_step import WorkflowStep
from app.schemas.workflow import WorkflowCreate

_MAX_LIST_LIMIT = 500


def create_workflow(db: Session, data: WorkflowCreate) -> Workflow:
    """Create one workflow with its ordered steps in a single transaction.

    Rolls back and re-raises if any step is invalid at the database layer.
    """
    workflow = Workflow(
        name=data.name,
        description=data.description,
        input_payload=data.input_payload,
    )
    for step_data in data.steps:
        workflow.steps.append(
            WorkflowStep(
                name=step_data.name,
                position=step_data.position,
                agent_type=step_data.agent_type,
                input_payload=step_data.input_payload,
                max_attempts=step_data.max_attempts,
                compensation_handler=step_data.compensation_handler,
            )
        )

    db.add(workflow)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise

    persisted = get_workflow(db, workflow.id)
    if persisted is None:
        raise RuntimeError("workflow persistence failed unexpectedly")
    return persisted


def get_workflow(db: Session, workflow_id: str) -> Workflow | None:
    """Retrieve a workflow by ID with its ordered steps and attempt history.

    Uses `populate_existing=True` so a workflow already present in this session's
    identity map (e.g. just created with steps appended out of position order) is
    refreshed from the database, applying the steps/attempts ordering.
    """
    stmt = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .options(selectinload(Workflow.steps).selectinload(WorkflowStep.attempts))
        .execution_options(populate_existing=True)
    )
    return db.scalars(stmt).one_or_none()


def list_workflows(db: Session, limit: int = 50) -> list[Workflow]:
    """List workflows ordered by newest creation time first, bounded by `limit`."""
    if limit <= 0 or limit > _MAX_LIST_LIMIT:
        raise ValueError(f"limit must be between 1 and {_MAX_LIST_LIMIT}")
    stmt = select(Workflow).order_by(Workflow.created_at.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def transition_workflow(db: Session, workflow_id: str, target: WorkflowStatus) -> Workflow:
    """Apply a validated workflow status transition and persist it."""
    workflow = db.get(Workflow, workflow_id)
    if workflow is None:
        raise ValueError(f"workflow '{workflow_id}' not found")

    try:
        apply_workflow_transition(workflow, target)
        db.commit()
    except InvalidStateTransition:
        db.rollback()
        raise
    return workflow


def transition_step(db: Session, step_id: str, target: StepStatus) -> WorkflowStep:
    """Apply a validated workflow-step status transition and persist it."""
    step = db.get(WorkflowStep, step_id)
    if step is None:
        raise ValueError(f"workflow step '{step_id}' not found")

    try:
        apply_step_transition(step, target)
        db.commit()
    except InvalidStateTransition:
        db.rollback()
        raise
    return step


def create_step_attempt(db: Session, step_id: str) -> StepAttempt:
    """Allocate and persist the next attempt for a step, incrementing its attempt count."""
    step = db.get(WorkflowStep, step_id)
    if step is None:
        raise ValueError(f"workflow step '{step_id}' not found")

    attempt_number = step.attempt_count + 1
    attempt = StepAttempt(step_id=step.id, attempt_number=attempt_number)
    step.attempt_count = attempt_number
    step.updated_at = datetime.now(UTC)

    db.add(attempt)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise
    return attempt


def set_workflow_result(
    db: Session,
    workflow_id: str,
    *,
    output_payload: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> Workflow:
    """Persist a workflow's aggregated output and/or error message, without changing its status."""
    workflow = db.get(Workflow, workflow_id)
    if workflow is None:
        raise ValueError(f"workflow '{workflow_id}' not found")

    workflow.output_payload = output_payload
    workflow.error_message = error_message

    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise
    return workflow


def complete_step_attempt(
    db: Session,
    attempt_id: str,
    *,
    status: AttemptStatus,
    output_payload: dict[str, Any] | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
) -> StepAttempt:
    """Record the terminal outcome of a step attempt."""
    if status is AttemptStatus.RUNNING:
        raise ValueError("complete_step_attempt requires a terminal attempt status")

    attempt = db.get(StepAttempt, attempt_id)
    if attempt is None:
        raise ValueError(f"step attempt '{attempt_id}' not found")

    attempt.status = status
    attempt.completed_at = datetime.now(UTC)
    attempt.output_payload = output_payload
    attempt.error_type = error_type
    attempt.error_message = error_message

    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise
    return attempt


def set_compensation_summary(db: Session, workflow_id: str, summary: dict[str, Any]) -> Workflow:
    """Persist a workflow's compensation summary.

    Deliberately separate from `set_workflow_result`: that function always
    overwrites both `output_payload` and `error_message` (by design, for the
    execution success/failure paths), which would erase the original
    execution output or failure reason if reused here. This function touches
    only `compensation_summary`.
    """
    workflow = db.get(Workflow, workflow_id)
    if workflow is None:
        raise ValueError(f"workflow '{workflow_id}' not found")

    workflow.compensation_summary = summary

    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise
    return workflow


def create_compensation_attempt(
    db: Session, step_id: str, *, handler_name: str
) -> CompensationAttempt:
    """Allocate and persist the next compensation attempt for a step."""
    step = db.get(WorkflowStep, step_id)
    if step is None:
        raise ValueError(f"workflow step '{step_id}' not found")

    attempt_number = len(step.compensation_attempts) + 1
    attempt = CompensationAttempt(
        step_id=step.id, attempt_number=attempt_number, handler_name=handler_name
    )

    db.add(attempt)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise
    return attempt


def complete_compensation_attempt(
    db: Session,
    attempt_id: str,
    *,
    status: CompensationAttemptStatus,
    output_payload: dict[str, Any] | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
) -> CompensationAttempt:
    """Record the terminal outcome of a compensation attempt."""
    if status is CompensationAttemptStatus.RUNNING:
        raise ValueError("complete_compensation_attempt requires a terminal attempt status")

    attempt = db.get(CompensationAttempt, attempt_id)
    if attempt is None:
        raise ValueError(f"compensation attempt '{attempt_id}' not found")

    attempt.status = status
    attempt.completed_at = datetime.now(UTC)
    attempt.output_payload = output_payload
    attempt.error_type = error_type
    attempt.error_message = error_message

    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise
    return attempt
