"""In-memory status enumerations for the graph scheduler.

Deliberately separate from `app.models.enums.WorkflowStatus`/`StepStatus`,
which remain the persisted, unchanged status enums for the live sequential
engine (rule: don't rename existing persisted statuses without a documented
migration). These cover the fuller status vocabulary the graph scheduler
needs — `ready`, `cancelling`, `planning`, etc. — for state that exists only
for the duration of one `GraphScheduler.run()` call.
"""

from enum import StrEnum


class GraphWorkflowStatus(StrEnum):
    PENDING = "pending"
    PLANNING = "planning"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class GraphStepStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"


GRAPH_WORKFLOW_TERMINAL_STATES: frozenset[GraphWorkflowStatus] = frozenset(
    {GraphWorkflowStatus.SUCCEEDED, GraphWorkflowStatus.FAILED, GraphWorkflowStatus.CANCELLED}
)

GRAPH_STEP_TERMINAL_STATES: frozenset[GraphStepStatus] = frozenset(
    {
        GraphStepStatus.SUCCEEDED,
        GraphStepStatus.FAILED,
        GraphStepStatus.SKIPPED,
        GraphStepStatus.CANCELLED,
    }
)
