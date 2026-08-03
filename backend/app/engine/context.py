"""Typed execution context threaded through sequential workflow step execution."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ExecutionContext:
    """Accumulates step outputs as a workflow executes.

    `previous_step_outputs` is keyed by stable step ID, not step name, since
    step names may repeat within a workflow. The persisted workflow input is
    never mutated; each successful step produces a new context instance.
    """

    workflow_id: str
    workflow_input: dict[str, Any]
    previous_step_outputs: dict[str, dict[str, Any]] = field(default_factory=dict)

    def with_step_output(self, step_id: str, output: dict[str, Any]) -> "ExecutionContext":
        """Return a new context with one more step's output recorded, in order."""
        return ExecutionContext(
            workflow_id=self.workflow_id,
            workflow_input=self.workflow_input,
            previous_step_outputs={**self.previous_step_outputs, step_id: output},
        )
