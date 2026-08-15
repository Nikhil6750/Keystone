"""Tests for `app.engine.orchestration.compiler`."""

from datetime import UTC, datetime

import pytest

from app.contracts.planning import TaskSpec, WorkflowPlan
from app.engine.orchestration.compiler import compile_workflow_create, topological_order
from app.engine.orchestration.errors import InvalidOrchestrationRequestError


def _task(key: str, **overrides: object) -> TaskSpec:
    base: dict[str, object] = {"key": key, "name": key, "task_type": "code_generation"}
    base.update(overrides)
    return TaskSpec.model_validate(base)


def _plan(tasks: list[TaskSpec]) -> WorkflowPlan:
    return WorkflowPlan(plan_id="plan-1", goal="goal", tasks=tasks, created_at=datetime.now(UTC))


def test_topological_order_respects_dependencies() -> None:
    tasks = [_task("c", depends_on=["a", "b"]), _task("a"), _task("b", depends_on=["a"])]
    ordered = topological_order(tasks)
    keys = [t.key for t in ordered]
    assert keys.index("a") < keys.index("b") < keys.index("c")


def test_topological_order_is_deterministic_tie_break() -> None:
    tasks = [_task("z"), _task("a"), _task("m")]
    ordered = topological_order(tasks)
    assert [t.key for t in ordered] == ["a", "m", "z"]


def test_topological_order_stable_across_calls() -> None:
    tasks = [_task("c", depends_on=["a"]), _task("a"), _task("b", depends_on=["a"])]
    first = [t.key for t in topological_order(tasks)]
    second = [t.key for t in topological_order(tasks)]
    assert first == second


def test_compile_workflow_create_assigns_positions_in_dependency_order() -> None:
    tasks = [_task("b", depends_on=["a"]), _task("a")]
    plan = _plan(tasks)
    workflow_create = compile_workflow_create(plan, {"a": "claude_code", "b": "codex"})
    assert [s.position for s in workflow_create.steps] == [0, 1]
    assert workflow_create.steps[0].name == "a"
    assert workflow_create.steps[0].agent_type == "claude_code"
    assert workflow_create.steps[1].name == "b"
    assert workflow_create.steps[1].agent_type == "codex"


def test_compile_workflow_create_uses_plan_goal_as_default_name() -> None:
    plan = _plan([_task("a")])
    workflow_create = compile_workflow_create(plan, {"a": "claude_code"})
    assert workflow_create.name == plan.goal


def test_compile_workflow_create_raises_for_unrouted_task() -> None:
    plan = _plan([_task("a"), _task("b")])
    with pytest.raises(InvalidOrchestrationRequestError):
        compile_workflow_create(plan, {"a": "claude_code"})


def test_compile_workflow_create_carries_input_payload() -> None:
    plan = _plan([_task("a", input_payload={"x": 1})])
    workflow_create = compile_workflow_create(plan, {"a": "claude_code"})
    assert workflow_create.steps[0].input_payload == {"x": 1}


def test_compile_workflow_create_is_deterministic() -> None:
    plan = _plan([_task("b", depends_on=["a"]), _task("a")])
    first = compile_workflow_create(plan, {"a": "claude_code", "b": "codex"})
    second = compile_workflow_create(plan, {"a": "claude_code", "b": "codex"})
    assert first == second
