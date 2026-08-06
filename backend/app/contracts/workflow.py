"""DAG-aware workflow definition contracts and the workflow event contract.

`WorkflowDefinition`/`WorkflowStepDefinition` are a new, additive shape: the
live `WorkflowCreate`/`WorkflowStepCreate` schemas (`app.schemas.workflow`)
and the position-ordered `Workflow`/`WorkflowStep` ORM models are unchanged
in this stage and remain the contract the current sequential engine and API
use. These new types add a `depends_on` graph on top of that, which Stage 2's
`engine.workflow.graph`/`validator` module will consume to build and execute
a real DAG.

Only structural well-formedness is validated here (unique step keys, `depends_on`
referencing declared keys, no self-dependency). Cycle detection and
topological ordering are graph algorithms that belong in Stage 2's dedicated
validator, not duplicated in this contract.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import StepStatus, WorkflowStatus

# Alias kept for exact parity with the contract name list; `StepStatus` is the
# canonical enum defined once in `app.models.enums` and used by persistence.
WorkflowStepStatus = StepStatus


class WorkflowStepDefinition(BaseModel):
    """One node in a DAG-aware workflow definition."""

    model_config = ConfigDict(extra="forbid")

    key: str
    name: str
    agent_type: str
    depends_on: list[str] = Field(default_factory=list)
    input_payload: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = 3
    timeout_seconds: float | None = None
    compensation_handler: str | None = None

    @field_validator("key", "name", "agent_type")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("max_attempts")
    @classmethod
    def _max_attempts_valid(cls, value: int) -> int:
        if value < 1:
            raise ValueError("max_attempts must be at least 1")
        return value

    @field_validator("timeout_seconds")
    @classmethod
    def _timeout_positive(cls, value: float | None) -> float | None:
        if value is not None and value <= 0:
            raise ValueError("timeout_seconds must be positive")
        return value

    @model_validator(mode="after")
    def _no_self_dependency(self) -> "WorkflowStepDefinition":
        if self.key in self.depends_on:
            raise ValueError(f"step '{self.key}' cannot depend on itself")
        if len(self.depends_on) != len(set(self.depends_on)):
            raise ValueError(f"step '{self.key}' has duplicate entries in depends_on")
        return self


class WorkflowDefinition(BaseModel):
    """A DAG-aware workflow definition: steps plus their declared dependencies."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None
    input_payload: dict[str, Any] = Field(default_factory=dict)
    steps: list[WorkflowStepDefinition] = Field(default_factory=list)
    concurrency_limit: int | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be empty")
        return value

    @field_validator("concurrency_limit")
    @classmethod
    def _concurrency_limit_valid(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("concurrency_limit must be at least 1")
        return value

    @model_validator(mode="after")
    def _unique_keys_and_known_dependencies(self) -> "WorkflowDefinition":
        keys = [step.key for step in self.steps]
        if len(keys) != len(set(keys)):
            raise ValueError("step keys must be unique within a workflow")
        known = set(keys)
        for step in self.steps:
            unknown = [dep for dep in step.depends_on if dep not in known]
            if unknown:
                raise ValueError(
                    f"step '{step.key}' depends on undeclared step(s): {', '.join(unknown)}"
                )
        return self


class WorkflowExecutionEvent(BaseModel):
    """One event in a workflow's execution timeline, for audit replay and SSE delivery."""

    model_config = ConfigDict(from_attributes=True)

    event_id: str
    workflow_id: str
    step_id: str | None = None
    event_type: str
    sequence_number: int
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "WorkflowDefinition",
    "WorkflowExecutionEvent",
    "WorkflowStatus",
    "WorkflowStepDefinition",
    "WorkflowStepStatus",
]
