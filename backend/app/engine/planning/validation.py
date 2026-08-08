"""Thin DAG structural validation helper for Stage 4D Workflow Planning.

Note: `WorkflowPlan` (`app.contracts.planning`) is the primary structural source of truth
and already enforces unique task keys, known dependencies, no self-dependencies, and DFS cycle
detection at the contract level. This module provides a thin helper for checking task lists before
`WorkflowPlan` instantiation if needed.
"""

from datetime import UTC

from app.contracts.planning import TaskSpec, WorkflowPlan


class PlannerValidationError(ValueError):
    """Raised when a task graph fails validation checks."""


def validate_task_graph(tasks: list[TaskSpec]) -> None:
    """Validate task list structure.

    Primary validation is enforced by `WorkflowPlan` contract itself.
    """
    if not tasks:
        raise PlannerValidationError("Workflow plan must contain at least one task")

    # Delegate structural validation directly to WorkflowPlan model validation
    try:
        # Create temporary dummy WorkflowPlan to leverage contract validation
        from datetime import datetime

        WorkflowPlan(
            plan_id="dummy_val_id",
            goal="dummy validation goal",
            tasks=tasks,
            created_at=datetime(1970, 1, 1, tzinfo=UTC),
        )
    except ValueError as exc:
        raise PlannerValidationError(str(exc)) from exc


__all__ = ["PlannerValidationError", "validate_task_graph"]
