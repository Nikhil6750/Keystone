"""Validated state-transition rules for the graph scheduler's in-memory
`GraphWorkflowStatus`/`GraphStepStatus`.

Mirrors the pattern of `app.engine.state_machine` (which remains the
validated transition table for the live, persisted
`WorkflowStatus`/`StepStatus`) but operates on plain enum values rather than
ORM instances, since this package has nothing persisted to mutate yet.

`GraphScheduler.run()` calls `transition_graph_workflow`/`transition_graph_step`
at every real state change during execution — this table is not just
documentation, it is the actual guard the scheduler validates against.
Retry-related states (`RETRYING`) and workflow/step compensation states
remain defined for future (Stage 3+) integration even though the current
scheduler does not itself produce them — do not remove them merely because
they are unused today.
"""

from app.engine.workflow.status import GraphStepStatus, GraphWorkflowStatus


class InvalidGraphStateTransition(ValueError):
    """Raised when a requested graph workflow/step transition is not permitted."""


GRAPH_WORKFLOW_TRANSITIONS: dict[GraphWorkflowStatus, frozenset[GraphWorkflowStatus]] = {
    GraphWorkflowStatus.PENDING: frozenset(
        {
            GraphWorkflowStatus.PLANNING,
            GraphWorkflowStatus.RUNNING,
            GraphWorkflowStatus.CANCELLING,
            GraphWorkflowStatus.CANCELLED,
        }
    ),
    GraphWorkflowStatus.PLANNING: frozenset(
        {
            GraphWorkflowStatus.RUNNING,
            GraphWorkflowStatus.CANCELLING,
            GraphWorkflowStatus.CANCELLED,
        }
    ),
    GraphWorkflowStatus.RUNNING: frozenset(
        {
            GraphWorkflowStatus.CANCELLING,
            GraphWorkflowStatus.SUCCEEDED,
            GraphWorkflowStatus.FAILED,
        }
    ),
    GraphWorkflowStatus.CANCELLING: frozenset({GraphWorkflowStatus.CANCELLED}),
    GraphWorkflowStatus.SUCCEEDED: frozenset(),
    GraphWorkflowStatus.FAILED: frozenset(),
    GraphWorkflowStatus.CANCELLED: frozenset(),
}

GRAPH_STEP_TRANSITIONS: dict[GraphStepStatus, frozenset[GraphStepStatus]] = {
    GraphStepStatus.PENDING: frozenset(
        {GraphStepStatus.READY, GraphStepStatus.SKIPPED, GraphStepStatus.CANCELLED}
    ),
    GraphStepStatus.READY: frozenset(
        {
            GraphStepStatus.RUNNING,
            GraphStepStatus.CANCELLING,
            GraphStepStatus.CANCELLED,
            GraphStepStatus.SKIPPED,
        }
    ),
    GraphStepStatus.RUNNING: frozenset(
        {
            GraphStepStatus.SUCCEEDED,
            GraphStepStatus.FAILED,
            GraphStepStatus.RETRYING,
            GraphStepStatus.CANCELLING,
        }
    ),
    GraphStepStatus.RETRYING: frozenset(
        {GraphStepStatus.RUNNING, GraphStepStatus.FAILED, GraphStepStatus.CANCELLED}
    ),
    GraphStepStatus.CANCELLING: frozenset({GraphStepStatus.CANCELLED}),
    GraphStepStatus.SUCCEEDED: frozenset(),
    GraphStepStatus.FAILED: frozenset(),
    GraphStepStatus.SKIPPED: frozenset(),
    GraphStepStatus.CANCELLED: frozenset(),
}


def transition_graph_workflow(
    current: GraphWorkflowStatus, target: GraphWorkflowStatus
) -> GraphWorkflowStatus:
    """Return `target` if the transition from `current` is permitted, else raise."""
    allowed = GRAPH_WORKFLOW_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidGraphStateTransition(
            f"cannot transition workflow from '{current.value}' to '{target.value}'"
        )
    return target


def transition_graph_step(current: GraphStepStatus, target: GraphStepStatus) -> GraphStepStatus:
    """Return `target` if the transition from `current` is permitted, else raise."""
    allowed = GRAPH_STEP_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidGraphStateTransition(
            f"cannot transition step from '{current.value}' to '{target.value}'"
        )
    return target


__all__ = [
    "GRAPH_STEP_TRANSITIONS",
    "GRAPH_WORKFLOW_TRANSITIONS",
    "InvalidGraphStateTransition",
    "transition_graph_step",
    "transition_graph_workflow",
]
