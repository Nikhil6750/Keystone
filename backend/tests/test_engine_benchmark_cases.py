"""Tests for Stage 7A BenchmarkCase validation, path safety, and input key safety."""

import pytest

from app.contracts.enums import BenchmarkEvaluatorType
from app.contracts.planning import ExpectedOutcome
from app.engine.benchmark.errors import MalformedBenchmarkCaseError
from app.engine.benchmark.models import BenchmarkCase


def test_valid_benchmark_case_creation() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        criteria={"expected": "world"},
    )
    case = BenchmarkCase(
        case_id="c1",
        task_type="text_gen",
        expected_outcome=expected,
        input_payload={"prompt": "hello"},
        timeout_seconds=15.0,
        repository_id="org/repo-a",
        metadata={"category": "smoke"},
    )
    assert case.case_id == "c1"
    assert case.repository_id == "org/repo-a"


def test_blank_case_id_or_task_type_rejected() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        criteria={"expected": "ok"},
    )
    with pytest.raises(MalformedBenchmarkCaseError, match="case_id must not be blank"):
        BenchmarkCase(case_id=" ", task_type="t1", expected_outcome=expected)

    with pytest.raises(MalformedBenchmarkCaseError, match="task_type must not be blank"):
        BenchmarkCase(case_id="c1", task_type="", expected_outcome=expected)


def test_non_positive_timeout_rejected() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        criteria={"expected": "ok"},
    )
    with pytest.raises(MalformedBenchmarkCaseError, match="timeout_seconds must be positive"):
        BenchmarkCase(
            case_id="c1",
            task_type="t1",
            expected_outcome=expected,
            timeout_seconds=0.0,
        )


def test_absolute_or_traversal_repository_id_rejected() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        criteria={"expected": "ok"},
    )

    with pytest.raises(MalformedBenchmarkCaseError, match="absolute filesystem path"):
        BenchmarkCase(
            case_id="c1",
            task_type="t1",
            expected_outcome=expected,
            repository_id="/var/lib/repo",
        )

    with pytest.raises(MalformedBenchmarkCaseError, match="absolute filesystem path"):
        BenchmarkCase(
            case_id="c1",
            task_type="t1",
            expected_outcome=expected,
            repository_id=r"C:\Projects\repo",
        )

    with pytest.raises(MalformedBenchmarkCaseError, match="absolute filesystem path"):
        BenchmarkCase(
            case_id="c1",
            task_type="t1",
            expected_outcome=expected,
            repository_id="repo/../other",
        )


def test_relative_repository_id_accepted() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        criteria={"expected": "ok"},
    )
    case = BenchmarkCase(
        case_id="c1",
        task_type="t1",
        expected_outcome=expected,
        repository_id="backend/subproject",
    )
    assert case.repository_id == "backend/subproject"
