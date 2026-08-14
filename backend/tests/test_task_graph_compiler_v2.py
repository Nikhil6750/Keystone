"""Adversarial and Unit Tests for TaskGraphCompilerV2."""

import pytest

from app.contracts.enums import AgentCapability, BenchmarkEvaluatorType
from app.engine.planning.compiler import (
    ComplexityLevel,
    TaskGraphCompilerV2,
)


def test_compiler_requires_non_empty_goal() -> None:
    compiler = TaskGraphCompilerV2()
    with pytest.raises(ValueError, match="goal must not be empty"):
        compiler.compile("")
    with pytest.raises(ValueError, match="goal must not be empty"):
        compiler.compile("   ")


# Test the 10 distinct adversarial goals from the certification specification


def test_goal_1_modify_one_python_function() -> None:
    compiler = TaskGraphCompilerV2()
    nodes = compiler.compile("Modify one Python function in main.py to handle empty input")
    assert len(nodes) == 2
    assert nodes[0].task_type == "code_modification"
    assert nodes[0].target_files == ["main.py"]
    assert nodes[0].estimated_complexity == ComplexityLevel.TRIVIAL
    assert nodes[1].task_type == "objective_verification"


def test_goal_2_build_landing_page() -> None:
    compiler = TaskGraphCompilerV2()
    nodes = compiler.compile("Build a landing page for our new product")
    assert len(nodes) == 3
    assert nodes[0].task_type == "code_generation"
    assert "index.html" in nodes[0].target_files
    assert nodes[1].task_type == "test_generation"
    assert nodes[2].task_type == "objective_verification"
    # No backend nodes should exist
    assert not any(n.task_type == "backend_development" for n in nodes)


def test_goal_3_add_authentication_to_existing_fastapi_app() -> None:
    compiler = TaskGraphCompilerV2()
    nodes = compiler.compile("Add authentication to an existing FastAPI app")
    assert len(nodes) == 3
    assert nodes[0].task_type == "backend_development"
    assert nodes[0].title == "Implement authentication service"
    assert nodes[1].task_type == "test_generation"
    assert nodes[1].target_files == ["test_auth.py"]
    assert nodes[2].task_type == "objective_verification"


def test_goal_4_add_postgresql_migration() -> None:
    compiler = TaskGraphCompilerV2()
    nodes = compiler.compile("Add a PostgreSQL migration for user profiles")
    assert len(nodes) == 3
    assert nodes[0].task_type == "database_migration"
    assert nodes[1].task_type == "schema_validation"
    assert nodes[2].task_type == "objective_verification"


def test_goal_5_build_cli_utility() -> None:
    compiler = TaskGraphCompilerV2()
    nodes = compiler.compile("Build a CLI utility for batch renaming files")
    assert len(nodes) == 3
    assert nodes[0].task_type == "cli_development"
    assert nodes[1].task_type == "cli_testing"
    assert nodes[2].task_type == "objective_verification"


def test_goal_6_refactor_existing_module() -> None:
    compiler = TaskGraphCompilerV2()
    nodes = compiler.compile("Refactor an existing module in module.py to use dependency injection")
    assert len(nodes) == 3
    assert nodes[0].task_type == "refactoring"
    assert nodes[1].task_type == "regression_testing"
    assert nodes[2].task_type == "objective_verification"


def test_goal_7_create_data_pipeline() -> None:
    compiler = TaskGraphCompilerV2()
    nodes = compiler.compile("Create a data pipeline for ingestion and ETL transformations")
    assert len(nodes) == 3
    assert nodes[0].task_type == "data_pipeline_development"
    assert nodes[1].task_type == "pipeline_testing"
    assert nodes[2].task_type == "objective_verification"
    # Must NOT collapse into CLI utility
    assert not any("cli" in n.task_type for n in nodes)


def test_goal_8_add_tests_only() -> None:
    compiler = TaskGraphCompilerV2()
    nodes = compiler.compile("Add tests only for python backend models")
    assert len(nodes) == 2
    assert nodes[0].task_type == "test_generation"
    assert nodes[1].task_type == "objective_verification"
    # Must NOT create unrelated code implementation tasks
    disallowed = ("code_generation", "backend_development", "frontend_development")
    assert not any(n.task_type in disallowed for n in nodes)


def test_goal_9_build_calculator() -> None:
    compiler = TaskGraphCompilerV2()
    nodes = compiler.compile("Build a calculator web application")
    assert len(nodes) == 3
    assert nodes[0].task_type == "code_generation"
    assert nodes[1].task_type == "test_generation"
    assert nodes[2].task_type == "objective_verification"


def test_goal_10_build_fullstack_app() -> None:
    compiler = TaskGraphCompilerV2()
    nodes = compiler.compile("Build a full-stack app with React UI and Python API")
    assert len(nodes) == 5
    task_types = [n.task_type for n in nodes]
    assert task_types == [
        "frontend_development",
        "backend_development",
        "test_generation",
        "integration",
        "objective_verification",
    ]

    # Verify parallel safety for independent frontend and backend nodes
    fe_node = next(n for n in nodes if n.task_type == "frontend_development")
    be_node = next(n for n in nodes if n.task_type == "backend_development")
    int_node = next(n for n in nodes if n.task_type == "integration")

    assert fe_node.parallel_safe is True
    assert be_node.parallel_safe is True
    assert int_node.parallel_safe is False  # Shared files and dependent
    assert "T1" in int_node.dependencies
    assert "T2" in int_node.dependencies


def test_derive_parallel_safety_enforces_bounds_and_ownership() -> None:
    compiler = TaskGraphCompilerV2()

    # When file ownership is UNKNOWN, parallel_safe is False
    nodes = compiler.compile("Do some freeform generic work")
    assert all(not n.parallel_safe for n in nodes)


def test_task_graph_bounds_enforced() -> None:
    compiler = TaskGraphCompilerV2()
    # Test valid bounds on fullstack graph
    nodes = compiler.compile("Build a fullstack web and api platform")
    assert len(nodes) <= TaskGraphCompilerV2.MAX_TASKS
    depth = compiler._calculate_dag_depth(nodes)
    assert depth <= TaskGraphCompilerV2.MAX_DEPTH


def test_to_task_spec_conversion() -> None:
    compiler = TaskGraphCompilerV2()
    nodes = compiler.compile("Build a landing page")
    specs = [n.to_task_spec() for n in nodes]
    assert len(specs) == len(nodes)
    assert specs[0].key == "T1"
    assert AgentCapability.CODE_GENERATION in specs[0].required_capabilities
    assert specs[1].expected_outcome is not None
    assert specs[1].expected_outcome.evaluator_type == BenchmarkEvaluatorType.UNIT_TEST
