"""Validated state-transition rules for workflows and workflow steps."""

from datetime import UTC, datetime

from app.models.enums import StepStatus, WorkflowStatus
from app.models.workflow import Workflow
from app.models.workflow_step import WorkflowStep


class InvalidStateTransition(ValueError):
    """Raised when a workflow or step state transition is not permitted."""


WORKFLOW_TRANSITIONS: dict[WorkflowStatus, frozenset[WorkflowStatus]] = {
    WorkflowStatus.PENDING: frozenset({WorkflowStatus.RUNNING, WorkflowStatus.CANCELLED}),
    WorkflowStatus.RUNNING: frozenset(
        {
            WorkflowStatus.SUCCEEDED,
            WorkflowStatus.FAILED,
            WorkflowStatus.COMPENSATING,
            WorkflowStatus.CANCELLED,
        }
    ),
    WorkflowStatus.FAILED: frozenset({WorkflowStatus.COMPENSATING}),
    WorkflowStatus.COMPENSATING: frozenset({WorkflowStatus.COMPENSATED, WorkflowStatus.FAILED}),
    WorkflowStatus.SUCCEEDED: frozenset(),
    WorkflowStatus.COMPENSATED: frozenset(),
    WorkflowStatus.CANCELLED: frozenset(),
}

WORKFLOW_TERMINAL_STATES: frozenset[WorkflowStatus] = frozenset(
    {WorkflowStatus.SUCCEEDED, WorkflowStatus.COMPENSATED, WorkflowStatus.CANCELLED}
)

_WORKFLOW_COMPLETING_STATES: frozenset[WorkflowStatus] = frozenset(
    {
        WorkflowStatus.SUCCEEDED,
        WorkflowStatus.FAILED,
        WorkflowStatus.COMPENSATED,
        WorkflowStatus.CANCELLED,
    }
)

STEP_TRANSITIONS: dict[StepStatus, frozenset[StepStatus]] = {
    StepStatus.PENDING: frozenset({StepStatus.RUNNING, StepStatus.SKIPPED, StepStatus.CANCELLED}),
    StepStatus.RUNNING: frozenset(
        {
            StepStatus.SUCCEEDED,
            StepStatus.FAILED,
            StepStatus.RETRYING,
            StepStatus.CANCELLED,
        }
    ),
    StepStatus.FAILED: frozenset({StepStatus.RETRYING, StepStatus.COMPENSATING}),
    StepStatus.RETRYING: frozenset({StepStatus.RUNNING, StepStatus.FAILED, StepStatus.CANCELLED}),
    StepStatus.SUCCEEDED: frozenset({StepStatus.COMPENSATING}),
    StepStatus.COMPENSATING: frozenset({StepStatus.COMPENSATED, StepStatus.FAILED}),
    StepStatus.COMPENSATED: frozenset(),
    StepStatus.SKIPPED: frozenset(),
    StepStatus.CANCELLED: frozenset(),
}

STEP_TERMINAL_STATES: frozenset[StepStatus] = frozenset(
    {StepStatus.COMPENSATED, StepStatus.SKIPPED, StepStatus.CANCELLED}
)

_STEP_COMPLETING_STATES: frozenset[StepStatus] = frozenset(
    {
        StepStatus.SUCCEEDED,
        StepStatus.FAILED,
        StepStatus.COMPENSATED,
        StepStatus.CANCELLED,
        StepStatus.SKIPPED,
    }
)


def transition_workflow(workflow: Workflow, target: WorkflowStatus) -> Workflow:
    """Validate and apply a workflow status transition in place.

    Raises `InvalidStateTransition` and leaves the workflow unchanged if the
    transition is not permitted.
    """
    current = WorkflowStatus(workflow.status)
    allowed = WORKFLOW_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidStateTransition(
            f"Cannot transition workflow from '{current.value}' to '{target.value}'"
        )

    now = datetime.now(UTC)
    workflow.status = target
    if target is WorkflowStatus.RUNNING and workflow.started_at is None:
        workflow.started_at = now
    if target in _WORKFLOW_COMPLETING_STATES:
        workflow.completed_at = now
    workflow.updated_at = now
    workflow.version += 1
    return workflow


def transition_step(step: WorkflowStep, target: StepStatus) -> WorkflowStep:
    """Validate and apply a workflow-step status transition in place.

    Raises `InvalidStateTransition` and leaves the step unchanged if the
    transition is not permitted.
    """
    current = StepStatus(step.status)
    allowed = STEP_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidStateTransition(
            f"Cannot transition step from '{current.value}' to '{target.value}'"
        )

    now = datetime.now(UTC)
    step.status = target
    if target is StepStatus.RUNNING and step.started_at is None:
        step.started_at = now
    if target in _STEP_COMPLETING_STATES:
        step.completed_at = now
    step.updated_at = now
    return step
