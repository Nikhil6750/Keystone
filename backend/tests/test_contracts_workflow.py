"""Tests for the DAG-aware WorkflowDefinition/WorkflowStepDefinition contracts."""

from typing import Any

import pytest
from pydantic import ValidationError

from app.contracts.workflow import WorkflowDefinition, WorkflowStepDefinition


def _step(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"key": "a", "name": "step-a", "agent_type": "demo"}
    base.update(overrides)
    return base


def test_linear_dependency_chain_is_valid() -> None:
    definition = WorkflowDefinition.model_validate(
        {
            "name": "linear",
            "steps": [
                _step(key="a"),
                _step(key="b", depends_on=["a"]),
                _step(key="c", depends_on=["b"]),
            ],
        }
    )
    assert [s.key for s in definition.steps] == ["a", "b", "c"]


def test_fan_out_fan_in_dependencies_are_valid() -> None:
    definition = WorkflowDefinition.model_validate(
        {
            "name": "fan",
            "steps": [
                _step(key="a"),
                _step(key="b", depends_on=["a"]),
                _step(key="c", depends_on=["a"]),
                _step(key="d", depends_on=["b", "c"]),
            ],
        }
    )
    assert definition.steps[-1].depends_on == ["b", "c"]


def test_unknown_dependency_is_rejected() -> None:
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate(
            {"name": "bad", "steps": [_step(key="a", depends_on=["missing"])]}
        )


def test_duplicate_step_keys_are_rejected() -> None:
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate(
            {"name": "dup", "steps": [_step(key="a"), _step(key="a")]}
        )


def test_self_dependency_is_rejected() -> None:
    with pytest.raises(ValidationError):
        WorkflowStepDefinition.model_validate(_step(key="a", depends_on=["a"]))


def test_duplicate_dependency_entries_are_rejected() -> None:
    with pytest.raises(ValidationError):
        WorkflowStepDefinition.model_validate(_step(key="a", depends_on=["b", "b"]))


def test_blank_step_name_is_rejected() -> None:
    with pytest.raises(ValidationError):
        WorkflowStepDefinition.model_validate(_step(name="  "))


def test_negative_concurrency_limit_is_rejected() -> None:
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate({"name": "x", "steps": [], "concurrency_limit": 0})


def test_independent_parallel_steps_have_no_dependencies() -> None:
    definition = WorkflowDefinition.model_validate(
        {"name": "parallel", "steps": [_step(key="a"), _step(key="b"), _step(key="c")]}
    )
    assert all(step.depends_on == [] for step in definition.steps)
