"""Pydantic schemas for workflow domain objects."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import AttemptStatus, CompensationAttemptStatus, StepStatus, WorkflowStatus


class WorkflowStepCreate(BaseModel):
    """Client-supplied data for one step of a workflow being created."""

    model_config = ConfigDict(extra="forbid")

    name: str
    position: int
    agent_type: str
    input_payload: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = 3
    compensation_handler: str | None = None

    @field_validator("name", "agent_type")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("position")
    @classmethod
    def _position_nonnegative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("position must be zero or greater")
        return value

    @field_validator("max_attempts")
    @classmethod
    def _max_attempts_valid(cls, value: int) -> int:
        if value < 1:
            raise ValueError("max_attempts must be at least 1")
        return value


class WorkflowCreate(BaseModel):
    """Client-supplied data to create a new workflow and its ordered steps."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None
    input_payload: dict[str, Any] = Field(default_factory=dict)
    steps: list[WorkflowStepCreate] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be empty")
        return value

    @model_validator(mode="after")
    def _unique_step_positions(self) -> "WorkflowCreate":
        positions = [step.position for step in self.steps]
        if len(positions) != len(set(positions)):
            raise ValueError("step positions must be unique within a workflow")
        return self


class StepAttemptRead(BaseModel):
    """Serialized representation of one step execution attempt."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    step_id: str
    attempt_number: int
    status: AttemptStatus
    started_at: datetime
    completed_at: datetime | None
    output_payload: dict[str, Any] | None
    error_type: str | None
    error_message: str | None


class CompensationAttemptRead(BaseModel):
    """Serialized representation of one compensation-handler invocation."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    step_id: str
    attempt_number: int
    handler_name: str
    status: CompensationAttemptStatus
    started_at: datetime
    completed_at: datetime | None
    output_payload: dict[str, Any] | None
    error_type: str | None
    error_message: str | None


class WorkflowStepRead(BaseModel):
    """Serialized representation of a workflow step."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_id: str
    name: str
    position: int
    agent_type: str
    status: StepStatus
    input_payload: dict[str, Any]
    output_payload: dict[str, Any] | None
    error_message: str | None
    max_attempts: int
    attempt_count: int
    compensation_handler: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    attempts: list[StepAttemptRead] = Field(default_factory=list)
    compensation_attempts: list[CompensationAttemptRead] = Field(default_factory=list)


class WorkflowRead(BaseModel):
    """Serialized representation of a workflow and its ordered steps."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    status: WorkflowStatus
    input_payload: dict[str, Any]
    output_payload: dict[str, Any] | None
    error_message: str | None
    compensation_summary: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    version: int
    steps: list[WorkflowStepRead] = Field(default_factory=list)


class WorkflowListResponse(BaseModel):
    """Response envelope for `GET /api/v1/workflows`."""

    model_config = ConfigDict(from_attributes=True)

    items: list[WorkflowRead]
    count: int
