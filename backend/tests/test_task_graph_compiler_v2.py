"""Unit tests for TaskGraphCompilerV2 (Agent-Independent DAG Decomposition)."""

import pytest

from app.contracts.enums import AgentCapability
from app.engine.planning.compiler import (
    TargetFileOwnership,
    TaskGraphCompilerV2,
)


def test_compiler_requires_non_empty_goal() -> None:
    compiler = TaskGraphCompilerV2()
    with pytest.raises(ValueError, match="goal must not be empty"):
        compiler.compile("")


def test_compiler_decomposes_simple_calculator_goal() -> None:
    compiler = TaskGraphCompilerV2()
    goal = "Build a polished calculator web application using HTML, CSS and JavaScript."
    nodes = compiler.compile(goal)

    assert len(nodes) == 3
    node_ids = [n.task_id for n in nodes]
    assert node_ids == ["T1", "T2", "T3"]

    # T1
    t1 = nodes[0]
    assert t1.task_id == "T1"
    assert t1.task_type == "code_generation"
    assert "index.html" in t1.target_files
    assert "styles.css" in t1.target_files
    assert "script.js" in t1.target_files
    assert t1.target_files_ownership == TargetFileOwnership.KNOWN
    assert AgentCapability.CODE_GENERATION in t1.required_capabilities
    assert AgentCapability.FILE_EDITING in t1.required_capabilities

    # T2
    t2 = nodes[1]
    assert t2.task_id == "T2"
    assert t2.task_type == "test_generation"
    assert "T1" in t2.dependencies
    assert AgentCapability.TEST_GENERATION in t2.required_capabilities
    assert "node --test" in str(t2.verification_requirements)

    # T3
    t3 = nodes[2]
    assert t3.task_id == "T3"
    assert t3.task_type == "objective_verification"
    assert "T2" in t3.dependencies


def test_compiler_decomposes_fullstack_app_with_parallel_tasks() -> None:
    compiler = TaskGraphCompilerV2()
    goal = "Build a small full-stack task tracker with HTML/CSS/JS frontend and Python API backend."
    nodes = compiler.compile(goal)

    assert len(nodes) == 5

    # T1 frontend, T2 backend, T3 tests can run concurrently
    t1 = next(n for n in nodes if n.task_id == "T1")
    t2 = next(n for n in nodes if n.task_id == "T2")
    t3 = next(n for n in nodes if n.task_id == "T3")

    assert t1.parallel_safe is True
    assert t2.parallel_safe is True
    assert t3.parallel_safe is True

    # Check target file separation
    assert set(t1.target_files).isdisjoint(set(t2.target_files))
    assert set(t2.target_files).isdisjoint(set(t3.target_files))


def test_compiler_is_agent_independent() -> None:
    """TaskGraphCompilerV2 must work identically without any agent parameters."""
    compiler = TaskGraphCompilerV2()
    nodes = compiler.compile("Implement user authentication endpoints")

    for node in nodes:
        spec = node.to_task_spec()
        # TaskSpec has no agent_type field by design
        assert not hasattr(spec, "agent_type")
        assert len(node.required_capabilities) > 0


def test_compiler_bounds_and_validates_task_count() -> None:
    compiler = TaskGraphCompilerV2()
    compiler.MAX_TASKS = 2

    with pytest.raises(ValueError, match="exceeds max task limit"):
        compiler.compile("Build a small full-stack task tracker app")


def test_compiler_enforces_max_depth() -> None:
    from app.engine.planning.compiler import CompiledTaskNode

    compiler = TaskGraphCompilerV2()
    compiler.MAX_DEPTH = 3

    n1 = CompiledTaskNode(task_id="T1", task_type="code_generation", title="T1", objective="o1")
    n2 = CompiledTaskNode(
        task_id="T2", task_type="code_generation", title="T2", objective="o2", dependencies=["T1"]
    )
    n3 = CompiledTaskNode(
        task_id="T3", task_type="code_generation", title="T3", objective="o3", dependencies=["T2"]
    )

    nodes_depth3 = [n1, n2, n3]
    compiler._validate_and_bound_graph(nodes_depth3)
    assert compiler._calculate_dag_depth(nodes_depth3) == 3

    n4 = CompiledTaskNode(
        task_id="T4", task_type="code_generation", title="T4", objective="o4", dependencies=["T3"]
    )
    nodes_depth4 = [n1, n2, n3, n4]

    with pytest.raises(ValueError, match="Task graph depth 4 exceeds max depth limit of 3"):
        compiler._validate_and_bound_graph(nodes_depth4)


def test_compiler_detects_cycles_and_duplicates() -> None:
    from app.engine.planning.compiler import CompiledTaskNode

    compiler = TaskGraphCompilerV2()

    # Cycle: T1 -> T2 -> T1
    c1 = CompiledTaskNode(
        task_id="T1", task_type="code_generation", title="T1", objective="o1", dependencies=["T2"]
    )
    c2 = CompiledTaskNode(
        task_id="T2", task_type="code_generation", title="T2", objective="o2", dependencies=["T1"]
    )
    with pytest.raises(ValueError, match="contains cycle"):
        compiler._validate_and_bound_graph([c1, c2])

    # Duplicate IDs: T1, T1
    d1 = CompiledTaskNode(task_id="T1", task_type="code_generation", title="T1", objective="o1")
    d2 = CompiledTaskNode(task_id="T1", task_type="code_generation", title="T1", objective="o1")
    with pytest.raises(ValueError, match="Duplicate task IDs"):
        compiler._validate_and_bound_graph([d1, d2])
