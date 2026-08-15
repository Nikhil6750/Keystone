"""Tests for app.engine.planning.validation."""

import pytest

from app.contracts.enums import AgentCapability
from app.contracts.planning import TaskSpec
from app.engine.planning.validation import PlannerValidationError, validate_task_graph


def test_valid_dag_passes() -> None:
    tasks = [
        TaskSpec(
            key="task1",
            name="Task 1",
            task_type="analysis",
            required_capabilities=[AgentCapability.GENERAL_REASONING],
        ),
        TaskSpec(
            key="task2",
            name="Task 2",
            task_type="code_generation",
            required_capabilities=[AgentCapability.CODE_GENERATION],
            depends_on=["task1"],
        ),
    ]
    validate_task_graph(tasks)  # Should not raise


def test_empty_tasks_fails() -> None:
    with pytest.raises(PlannerValidationError, match="must contain at least one task"):
        validate_task_graph([])


def test_duplicate_keys_fails() -> None:
    tasks = [
        TaskSpec(
            key="task1",
            name="Task 1",
            task_type="analysis",
            required_capabilities=[AgentCapability.GENERAL_REASONING],
        ),
        TaskSpec(
            key="task1",
            name="Task 1 duplicate",
            task_type="code_generation",
            required_capabilities=[AgentCapability.CODE_GENERATION],
        ),
    ]
    with pytest.raises(PlannerValidationError, match="unique"):
        validate_task_graph(tasks)


def test_missing_dependency_fails() -> None:
    tasks = [
        TaskSpec(
            key="task1",
            name="Task 1",
            task_type="analysis",
            required_capabilities=[AgentCapability.GENERAL_REASONING],
            depends_on=["non_existent_task"],
        ),
    ]
    with pytest.raises(PlannerValidationError, match="undeclared"):
        validate_task_graph(tasks)


def test_cycle_detection_fails() -> None:
    tasks = [
        TaskSpec(
            key="task1",
            name="Task 1",
            task_type="analysis",
            required_capabilities=[AgentCapability.GENERAL_REASONING],
            depends_on=["task2"],
        ),
        TaskSpec(
            key="task2",
            name="Task 2",
            task_type="code_generation",
            required_capabilities=[AgentCapability.CODE_GENERATION],
            depends_on=["task1"],
        ),
    ]
    with pytest.raises(PlannerValidationError, match="cycle"):
        validate_task_graph(tasks)
