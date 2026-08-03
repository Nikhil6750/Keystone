"""Tests for workflow Pydantic schemas."""

from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.workflow import WorkflowCreate, WorkflowStepCreate


def _step(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"name": "step-1", "position": 0, "agent_type": "mock"}
    base.update(overrides)
    return base


def test_empty_workflow_name_is_rejected() -> None:
    with pytest.raises(ValidationError):
        WorkflowCreate.model_validate({"name": "   ", "steps": []})


def test_empty_step_name_is_rejected() -> None:
    with pytest.raises(ValidationError):
        WorkflowStepCreate.model_validate(_step(name="  "))


def test_duplicate_step_positions_are_rejected_by_schema() -> None:
    with pytest.raises(ValidationError):
        WorkflowCreate.model_validate(
            {"name": "demo", "steps": [_step(position=0), _step(position=0)]}
        )


def test_invalid_max_attempts_is_rejected_by_schema() -> None:
    with pytest.raises(ValidationError):
        WorkflowStepCreate.model_validate(_step(max_attempts=0))


def test_client_supplied_internal_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        WorkflowCreate.model_validate({"name": "demo", "steps": [], "status": "running"})
