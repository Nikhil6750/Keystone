"""Tests for the Planner's output contracts: `TaskSpec`, `WorkflowPlan`,
`ExpectedOutcome`, `PlanningRequest`."""

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.contracts.enums import BenchmarkEvaluatorType
from app.contracts.planning import ExpectedOutcome, PlanningRequest, TaskSpec, WorkflowPlan

_NOW = datetime.now(UTC)


def _task(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"key": "a", "name": "step-a", "task_type": "analysis"}
    base.update(overrides)
    return base


def _plan(tasks: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "plan_id": "p1",
        "goal": "build auth",
        "tasks": tasks,
        "created_at": _NOW,
    }
    base.update(overrides)
    return base


def test_task_spec_cannot_contain_agent_type() -> None:
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(_task(agent_type="claude_code"))


def test_task_spec_rejects_blank_key_name_task_type() -> None:
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(_task(key="  "))
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(_task(name=""))
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(_task(task_type="   "))


def test_task_spec_rejects_self_dependency() -> None:
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(_task(key="a", depends_on=["a"]))


def test_task_spec_rejects_duplicate_depends_on_entries() -> None:
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(_task(depends_on=["b", "b"]))


def test_workflow_plan_rejects_duplicate_task_keys() -> None:
    with pytest.raises(ValidationError):
        WorkflowPlan.model_validate(_plan([_task(key="a"), _task(key="a")]))


def test_workflow_plan_rejects_unknown_dependency() -> None:
    with pytest.raises(ValidationError):
        WorkflowPlan.model_validate(_plan([_task(key="a", depends_on=["missing"])]))


def test_workflow_plan_rejects_a_two_task_cycle() -> None:
    with pytest.raises(ValidationError):
        WorkflowPlan.model_validate(
            _plan(
                [
                    _task(key="a", depends_on=["b"]),
                    _task(key="b", depends_on=["a"]),
                ]
            )
        )


def test_workflow_plan_rejects_a_longer_cycle() -> None:
    with pytest.raises(ValidationError):
        WorkflowPlan.model_validate(
            _plan(
                [
                    _task(key="a", depends_on=["c"]),
                    _task(key="b", depends_on=["a"]),
                    _task(key="c", depends_on=["b"]),
                ]
            )
        )


def test_workflow_plan_rejects_blank_plan_id_or_goal() -> None:
    with pytest.raises(ValidationError):
        WorkflowPlan.model_validate(_plan([], plan_id="  "))
    with pytest.raises(ValidationError):
        WorkflowPlan.model_validate(_plan([], goal=""))


def test_workflow_plan_accepts_a_valid_fan_out_fan_in_graph() -> None:
    plan = WorkflowPlan.model_validate(
        _plan(
            [
                _task(key="a"),
                _task(key="b", depends_on=["a"]),
                _task(key="c", depends_on=["a"]),
                _task(key="d", depends_on=["b", "c"]),
            ]
        )
    )
    assert [task.key for task in plan.tasks] == ["a", "b", "c", "d"]


def test_workflow_plan_preserves_deterministic_task_ordering() -> None:
    tasks = [_task(key="z"), _task(key="a"), _task(key="m")]
    plan = WorkflowPlan.model_validate(_plan(tasks))
    # Declared order preserved exactly, never resorted (e.g. alphabetically).
    assert [task.key for task in plan.tasks] == ["z", "a", "m"]

    dumped = plan.model_dump_json()
    restored = WorkflowPlan.model_validate_json(dumped)
    assert [task.key for task in restored.tasks] == ["z", "a", "m"]


def test_expected_outcome_reuses_benchmark_evaluator_type() -> None:
    outcome = ExpectedOutcome.model_validate(
        {"evaluator_type": BenchmarkEvaluatorType.UNIT_TEST, "criteria": {"min_passed": 5}}
    )
    assert outcome.evaluator_type is BenchmarkEvaluatorType.UNIT_TEST


def test_expected_outcome_rejects_blank_description_if_provided() -> None:
    with pytest.raises(ValidationError):
        ExpectedOutcome.model_validate(
            {"evaluator_type": BenchmarkEvaluatorType.LINT, "description": "   "}
        )


def test_task_spec_carries_an_expected_outcome() -> None:
    task = TaskSpec.model_validate(
        _task(
            expected_outcome={
                "evaluator_type": BenchmarkEvaluatorType.BUILD,
                "criteria": {"exit_code": 0},
            }
        )
    )
    assert task.expected_outcome is not None
    assert task.expected_outcome.evaluator_type is BenchmarkEvaluatorType.BUILD


def test_planning_request_rejects_blank_goal() -> None:
    with pytest.raises(ValidationError):
        PlanningRequest.model_validate({"goal": "   "})


def test_planning_request_default_constraints_are_permissive() -> None:
    request = PlanningRequest.model_validate({"goal": "build auth"})
    assert request.constraints.excluded_agent_types == []
    assert request.available_capabilities == []
    assert request.knowledge_context == []
