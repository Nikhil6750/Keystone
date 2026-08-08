"""Tests for the objective benchmarking contracts."""

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.contracts.benchmark import BenchmarkDefinition, BenchmarkResult
from app.contracts.enums import BenchmarkEvaluatorType
from app.contracts.errors import FailureCategory


def _definition(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "benchmark_id": "bench-1",
        "name": "exact match demo",
        "tasks": [
            {
                "task_id": "task-1",
                "input_payload": {"prompt": "add two numbers"},
                "expected": {"output": "4"},
                "evaluator_type": BenchmarkEvaluatorType.EXACT_MATCH,
            }
        ],
        "candidate_agent_types": ["demo"],
        "timeout_seconds": 30.0,
    }
    base.update(overrides)
    return base


def test_valid_definition_round_trips() -> None:
    definition = BenchmarkDefinition.model_validate(_definition())
    assert definition.tasks[0].evaluator_type is BenchmarkEvaluatorType.EXACT_MATCH


def test_definition_requires_at_least_one_task() -> None:
    with pytest.raises(ValidationError):
        BenchmarkDefinition.model_validate(_definition(tasks=[]))


def test_definition_requires_at_least_one_candidate() -> None:
    with pytest.raises(ValidationError):
        BenchmarkDefinition.model_validate(_definition(candidate_agent_types=[]))


def test_definition_rejects_non_positive_timeout() -> None:
    with pytest.raises(ValidationError):
        BenchmarkDefinition.model_validate(_definition(timeout_seconds=0))


def test_definition_rejects_zero_repeat_count() -> None:
    with pytest.raises(ValidationError):
        BenchmarkDefinition.model_validate(_definition(repeat_count=0))


def test_failed_result_preserves_failure_category() -> None:
    result = BenchmarkResult.model_validate(
        {
            "benchmark_id": "bench-1",
            "run_id": "run-1",
            "agent_type": "demo",
            "task_id": "task-1",
            "success": False,
            "failure_category": FailureCategory.TIMEOUT,
            "duration_ms": 1200.0,
            "created_at": datetime.now(UTC),
        }
    )
    assert result.success is False
    assert result.failure_category is FailureCategory.TIMEOUT


def _result(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "benchmark_id": "bench-1",
        "run_id": "run-1",
        "agent_type": "demo",
        "task_id": "task-1",
        "duration_ms": 1.0,
        "created_at": datetime.now(UTC),
    }
    base.update(overrides)
    return base


def test_successful_result_with_failure_category_is_rejected() -> None:
    with pytest.raises(ValidationError):
        BenchmarkResult.model_validate(
            _result(success=True, failure_category=FailureCategory.TIMEOUT)
        )


def test_failed_result_without_failure_category_is_rejected() -> None:
    with pytest.raises(ValidationError):
        BenchmarkResult.model_validate(_result(success=False))


def test_successful_result_without_failure_category_is_accepted() -> None:
    result = BenchmarkResult.model_validate(_result(success=True))
    assert result.failure_category is None


def test_warm_up_runs_are_distinguishable_from_measured_runs() -> None:
    result = BenchmarkResult.model_validate(
        {
            "benchmark_id": "bench-1",
            "run_id": "run-1",
            "agent_type": "demo",
            "task_id": "task-1",
            "success": True,
            "duration_ms": 5.0,
            "is_warm_up": True,
            "created_at": datetime.now(UTC),
        }
    )
    assert result.is_warm_up is True
