"""Test-only helpers for constructing a workflow already in a given state.

Bypasses the state machine and execution engine entirely — useful for testing
a service (like compensation) that operates on an already-terminal workflow,
without needing a full execution run first.
"""

from typing import Any

from sqlalchemy.orm import Session

from app.models.enums import StepStatus, WorkflowStatus
from app.models.workflow import Workflow
from app.models.workflow_step import WorkflowStep


def build_workflow_in_status(
    db_session: Session,
    *,
    workflow_status: WorkflowStatus,
    steps: list[dict[str, Any]],
    error_message: str | None = None,
) -> Workflow:
    """Directly construct a workflow (and its steps) already in a given status."""
    workflow = Workflow(
        name="demo",
        input_payload={},
        status=workflow_status,
        error_message=error_message,
        version=1,
    )
    for step_config in steps:
        step = WorkflowStep(
            name=step_config["name"],
            position=step_config["position"],
            agent_type=step_config.get("agent_type", "mock"),
            input_payload={},
            status=step_config.get("status", StepStatus.PENDING),
            compensation_handler=step_config.get("compensation_handler"),
            output_payload=step_config.get("output_payload"),
            max_attempts=step_config.get("max_attempts", 3),
            attempt_count=step_config.get("attempt_count", 0),
        )
        workflow.steps.append(step)
    db_session.add(workflow)
    db_session.commit()
    return workflow
