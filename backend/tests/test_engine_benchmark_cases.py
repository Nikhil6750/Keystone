"""Tests for Stage 7A BenchmarkSuite and BenchmarkCase construction and validation."""

import pytest

from app.contracts.enums import BenchmarkEvaluatorType
from app.contracts.planning import ExpectedOutcome
from app.engine.benchmark.errors import (
    MalformedBenchmarkCaseError,
    MalformedBenchmarkSuiteError,
)
from app.engine.benchmark.models import (
    MAX_BENCHMARK_REPEAT_COUNT,
    BenchmarkCase,
    BenchmarkSuite,
)


def test_valid_benchmark_case_and_suite() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        criteria={"expected": "hello world"},
    )
    case1 = BenchmarkCase(
        case_id="case-1",
        task_type="text_generation",
        expected_outcome=expected,
        input_payload={"prompt": "say hello"},
        timeout_seconds=10.0,
        repository_id="Nikhil6750/Keystone",
    )
    case2 = BenchmarkCase(
        case_id="case-2",
        task_type="text_generation",
        expected_outcome=expected,
    )
    suite = BenchmarkSuite(
        suite_id="suite-1",
        name="Test Suite",
        description="A test suite",
        cases=(case1, case2),
        repeat_count=3,
    )

    assert suite.suite_id == "suite-1"
    assert len(suite.cases) == 2
    assert suite.repeat_count == 3


def test_blank_case_id_rejected() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH, criteria={"expected": "x"}
    )
    with pytest.raises(MalformedBenchmarkCaseError, match="case_id must not be blank"):
        BenchmarkCase(
            case_id="  ",
            task_type="code_fix",
            expected_outcome=expected,
        )


def test_blank_task_type_rejected() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH, criteria={"expected": "x"}
    )
    with pytest.raises(MalformedBenchmarkCaseError, match="task_type must not be blank"):
        BenchmarkCase(
            case_id="case-1",
            task_type="",
            expected_outcome=expected,
        )


def test_invalid_timeout_rejected() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH, criteria={"expected": "x"}
    )
    with pytest.raises(MalformedBenchmarkCaseError, match="timeout_seconds must be positive"):
        BenchmarkCase(
            case_id="case-1",
            task_type="code_fix",
            expected_outcome=expected,
            timeout_seconds=-1.0,
        )


def test_unsafe_repository_id_rejected() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH, criteria={"expected": "x"}
    )
    with pytest.raises(MalformedBenchmarkCaseError, match="absolute filesystem path"):
        BenchmarkCase(
            case_id="case-1",
            task_type="code_fix",
            expected_outcome=expected,
            repository_id="/etc/passwd",
        )

    with pytest.raises(MalformedBenchmarkCaseError, match="absolute filesystem path"):
        BenchmarkCase(
            case_id="case-1",
            task_type="code_fix",
            expected_outcome=expected,
            repository_id="C:\\Windows\\System32",
        )


def test_empty_suite_cases_rejected() -> None:
    with pytest.raises(MalformedBenchmarkSuiteError, match="at least one case"):
        BenchmarkSuite(
            suite_id="suite-1",
            name="Empty Suite",
            cases=(),
        )


def test_duplicate_case_ids_rejected() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH, criteria={"expected": "x"}
    )
    case1 = BenchmarkCase(case_id="case-1", task_type="fix", expected_outcome=expected)
    case2 = BenchmarkCase(case_id="case-1", task_type="fix", expected_outcome=expected)
    with pytest.raises(MalformedBenchmarkSuiteError, match="duplicate case_id 'case-1'"):
        BenchmarkSuite(
            suite_id="suite-1",
            name="Dup Suite",
            cases=(case1, case2),
        )


def test_invalid_repeat_count_rejected() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH, criteria={"expected": "x"}
    )
    case = BenchmarkCase(case_id="case-1", task_type="fix", expected_outcome=expected)
    with pytest.raises(MalformedBenchmarkSuiteError, match="repeat_count must be between 1 and"):
        BenchmarkSuite(
            suite_id="suite-1",
            name="Suite",
            cases=(case,),
            repeat_count=0,
        )

    with pytest.raises(MalformedBenchmarkSuiteError, match="repeat_count must be between 1 and"):
        BenchmarkSuite(
            suite_id="suite-1",
            name="Suite",
            cases=(case,),
            repeat_count=MAX_BENCHMARK_REPEAT_COUNT + 1,
        )


def test_reasoning_shaped_keys_rejected() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH, criteria={"expected": "x"}
    )
    with pytest.raises(MalformedBenchmarkCaseError, match="chain_of_thought"):
        BenchmarkCase(
            case_id="case-1",
            task_type="fix",
            expected_outcome=expected,
            input_payload={"chain_of_thought": "secret reasoning"},
        )
