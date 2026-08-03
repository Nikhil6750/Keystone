"""Typed request passed to a compensation handler for one step."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CompensationRequest:
    """Everything a compensation handler needs to reverse one successful step."""

    workflow_id: str
    step_id: str
    step_name: str
    step_position: int
    agent_type: str
    compensation_handler: str
    workflow_input: dict[str, Any]
    step_input: dict[str, Any]
    step_output: dict[str, Any] | None
    previous_step_outputs: dict[str, dict[str, Any]]
    original_failure: str | None
