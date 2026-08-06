"""Tests for `WorkflowGraph`: adjacency, cycle detection, ready-step
calculation, and deterministic topological ordering."""

from typing import Any

import pytest

from app.contracts.workflow import WorkflowDefinition, WorkflowStepDefinition
from app.engine.workflow.exceptions import CycleDetectedError
from app.engine.workflow.graph import WorkflowGraph


def _step(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"key": "a", "name": "step-a", "agent_type": "demo"}
    base.update(overrides)
    return base


def _definition(steps: list[dict[str, Any]], **overrides: Any) -> WorkflowDefinition:
    base: dict[str, Any] = {"name": "wf", "steps": steps}
    base.update(overrides)
    return WorkflowDefinition.model_validate(base)


def test_linear_chain_topological_order() -> None:
    definition = _definition(
        [_step(key="a"), _step(key="b", depends_on=["a"]), _step(key="c", depends_on=["b"])]
    )
    graph = WorkflowGraph.from_definition(definition)
    assert graph.topological_order() == ["a", "b", "c"]


def test_fan_out_ready_steps_after_root_completes() -> None:
    definition = _definition(
        [
            _step(key="a"),
            _step(key="b", depends_on=["a"]),
            _step(key="c", depends_on=["a"]),
            _step(key="d", depends_on=["a"]),
        ]
    )
    graph = WorkflowGraph.from_definition(definition)
    assert graph.ready_steps(completed=set()) == ["a"]
    assert graph.ready_steps(completed={"a"}) == ["b", "c", "d"]


def test_fan_in_ready_only_after_all_dependencies_complete() -> None:
    definition = _definition(
        [
            _step(key="b"),
            _step(key="c"),
            _step(key="d"),
            _step(key="e", depends_on=["b", "c", "d"]),
        ]
    )
    graph = WorkflowGraph.from_definition(definition)
    # "d" has no dependencies of its own, so it's independently ready; "e" is
    # the one waiting on all three fan-in branches.
    assert graph.ready_steps(completed={"b", "c"}) == ["d"]
    assert graph.ready_steps(completed={"b", "c", "d"}) == ["e"]


def test_independent_parallel_steps_are_all_ready_immediately() -> None:
    definition = _definition([_step(key="a"), _step(key="b"), _step(key="c")])
    graph = WorkflowGraph.from_definition(definition)
    assert graph.ready_steps(completed=set()) == ["a", "b", "c"]


def test_ready_steps_excludes_already_scheduled() -> None:
    definition = _definition([_step(key="a"), _step(key="b")])
    graph = WorkflowGraph.from_definition(definition)
    assert graph.ready_steps(completed=set(), exclude={"a"}) == ["b"]


def test_two_step_cycle_is_rejected() -> None:
    # Cycle detection is deliberately not part of `WorkflowDefinition`'s own
    # validation (see its docstring) — "a" and "b" are both known, declared
    # keys, so the contract layer accepts this; only `WorkflowGraph` catches
    # the cycle.
    definition = _definition([_step(key="a", depends_on=["b"]), _step(key="b", depends_on=["a"])])
    with pytest.raises(CycleDetectedError) as exc_info:
        WorkflowGraph.from_definition(definition)
    assert "a" in exc_info.value.cycle
    assert "b" in exc_info.value.cycle


def test_longer_cycle_is_rejected() -> None:
    definition = _definition(
        [
            _step(key="a", depends_on=["c"]),
            _step(key="b", depends_on=["a"]),
            _step(key="c", depends_on=["b"]),
        ]
    )
    with pytest.raises(CycleDetectedError):
        WorkflowGraph.from_definition(definition)


def test_self_dependency_is_rejected_before_graph_construction() -> None:
    # WorkflowStepDefinition's own validator rejects this at the contract
    # layer; the graph module never has to handle a self-loop.
    with pytest.raises(Exception, match="cannot depend on itself"):
        WorkflowStepDefinition.model_validate(_step(key="a", depends_on=["a"]))


def test_transitive_dependents_covers_indirect_descendants() -> None:
    definition = _definition(
        [
            _step(key="a"),
            _step(key="b", depends_on=["a"]),
            _step(key="c", depends_on=["b"]),
            _step(key="d"),
        ]
    )
    graph = WorkflowGraph.from_definition(definition)
    assert graph.transitive_dependents("a") == {"b", "c"}
    assert graph.transitive_dependents("d") == set()


def test_topological_order_is_deterministic_across_calls() -> None:
    definition = _definition(
        [
            _step(key="a"),
            _step(key="b"),
            _step(key="c", depends_on=["a", "b"]),
        ]
    )
    graph = WorkflowGraph.from_definition(definition)
    first = graph.topological_order()
    second = graph.topological_order()
    assert first == second == ["a", "b", "c"]
