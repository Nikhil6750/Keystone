"""Shared domain exceptions for workflow lookup and execution."""

from app.models.enums import WorkflowStatus


class WorkflowNotFoundError(Exception):
    """Raised when a referenced workflow ID does not exist."""

    def __init__(self, workflow_id: str) -> None:
        self.workflow_id = workflow_id
        super().__init__(f"workflow '{workflow_id}' not found")


class InvalidWorkflowStateError(Exception):
    """Raised when execution is attempted on a workflow not in `PENDING` status."""

    def __init__(self, workflow_id: str, current_status: WorkflowStatus) -> None:
        self.workflow_id = workflow_id
        self.current_status = current_status
        super().__init__(
            f"workflow '{workflow_id}' cannot start execution from status '{current_status.value}'"
        )
