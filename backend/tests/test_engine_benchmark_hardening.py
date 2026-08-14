"""Hardening and regression tests for Stage 7A Benchmark Engine."""

from datetime import UTC, datetime

import pytest

from app.contracts.enums import AgentExecutionStatus, BenchmarkEvaluatorType
from app.contracts.errors import FailureCategory
from app.contracts.planning import ExpectedOutcome
from app.engine.benchmark.aggregation import percentile
from app.engine.benchmark.errors import (
    MalformedBenchmarkCaseError,
    MalformedBenchmarkSuiteError,
)
from app.engine.benchmark.executor import FakeBenchmarkExecutor
from app.engine.benchmark.models import (
    MAX_BENCHMARK_REPEAT_COUNT,
    BenchmarkCase,
    BenchmarkExecutionObservation,
    BenchmarkSuite,
)
from app.engine.benchmark.runner import BenchmarkRunner
from app.engine.verification.evaluators import ObservedOutcome


class RaisingBenchmarkExecutor:
    """Fake executor that raises an exception for specific agent/case."""

    def __init__(
        self, normal_responses: dict[tuple[str, str], BenchmarkExecutionObservation]
    ) -> None:
        self._normal = normal_responses

    def execute(
        self, *, agent_type: str, case: BenchmarkCase, repetition: int
    ) -> BenchmarkExecutionObservation:
        if agent_type == "buggy-agent":
            raise RuntimeError(
                "Database connection crashed! Sensitive connection string: postgresql://user:pass@host/db"
            )
        return self._normal[(agent_type, case.case_id)]


def test_runner_handles_executor_exception() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        criteria={"expected": "ok"},
    )
    case1 = BenchmarkCase(case_id="c1", task_type="t1", expected_outcome=expected)
    case2 = BenchmarkCase(case_id="c2", task_type="t1", expected_outcome=expected)
    suite = BenchmarkSuite(suite_id="s1", name="Suite", cases=(case1, case2))

    obs_ok = BenchmarkExecutionObservation(
        agent_type="good-agent",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        duration_ms=100.0,
        observed_outcome=ObservedOutcome(data={"output": "ok"}),
    )

    executor = RaisingBenchmarkExecutor(
        {
            ("good-agent", "c1"): obs_ok,
            ("good-agent", "c2"): obs_ok,
        }
    )

    runner = BenchmarkRunner()
    results, metrics = runner.run_suite(suite, ["good-agent", "buggy-agent"], executor)

    # Total results: 2 cases * 2 agents * 1 rep = 4
    assert len(results) == 4

    # Buggy agent results should be marked as FAILED with INTERNAL_ERROR
    buggy_metrics = metrics.agent_metrics["buggy-agent"]
    assert buggy_metrics.execution_count == 2
    assert buggy_metrics.execution_failure_count == 2
    assert buggy_metrics.verified_success_count == 0
    assert buggy_metrics.failure_categories["internal_error"] == 2

    # Verify no raw exception traceback or secret connection string is leaked into result error data
    for res in results:
        if res.agent_type == "buggy-agent":
            err_msg = res.verification_result.failure_reason or ""
            assert "postgresql" not in err_msg
            assert "pass" not in err_msg

    # Good agent still executed completely
    good_metrics = metrics.agent_metrics["good-agent"]
    assert good_metrics.verified_success_count == 2


def test_verification_inconclusive_and_human_review() -> None:
    # Missing 'expected' key triggers INCONCLUSIVE in verification
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        criteria={"expected": "something"},
    )
    case = BenchmarkCase(case_id="c1", task_type="t1", expected_outcome=expected)
    suite = BenchmarkSuite(suite_id="s1", name="Suite", cases=(case,))

    obs_inc = BenchmarkExecutionObservation(
        agent_type="a1",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        duration_ms=50.0,
        observed_outcome=ObservedOutcome(data={}),  # missing output triggers INCONCLUSIVE
    )
    executor = FakeBenchmarkExecutor({("a1", "c1"): obs_inc})

    runner = BenchmarkRunner()
    results, metrics = runner.run_suite(suite, ["a1"], executor)

    a1_m = metrics.agent_metrics["a1"]
    assert a1_m.execution_count == 1
    assert a1_m.execution_success_count == 1
    assert a1_m.verified_success_count == 0
    assert a1_m.verification_inconclusive_count == 1


def test_repeat_count_bounds() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        criteria={"expected": "x"},
    )
    case = BenchmarkCase(case_id="c1", task_type="t1", expected_outcome=expected)

    # 1 valid
    suite1 = BenchmarkSuite(suite_id="s1", name="S1", cases=(case,), repeat_count=1)
    assert suite1.repeat_count == 1

    # 20 valid
    suite20 = BenchmarkSuite(
        suite_id="s20", name="S20", cases=(case,), repeat_count=MAX_BENCHMARK_REPEAT_COUNT
    )
    assert suite20.repeat_count == MAX_BENCHMARK_REPEAT_COUNT

    # 0 rejected
    with pytest.raises(MalformedBenchmarkSuiteError, match="repeat_count must be between"):
        BenchmarkSuite(suite_id="s0", name="S0", cases=(case,), repeat_count=0)

    # 21 rejected
    with pytest.raises(MalformedBenchmarkSuiteError, match="repeat_count must be between"):
        BenchmarkSuite(
            suite_id="s21",
            name="S21",
            cases=(case,),
            repeat_count=MAX_BENCHMARK_REPEAT_COUNT + 1,
        )


def test_percentile_small_samples_and_ties() -> None:
    # n = 1
    assert percentile([10.0], 50) == 10.0
    assert percentile([10.0], 95) == 10.0

    # n = 2
    assert percentile([10.0, 20.0], 50) == 10.0
    assert percentile([10.0, 20.0], 95) == 20.0

    # n = 3
    assert percentile([10.0, 20.0, 30.0], 50) == 20.0
    assert percentile([10.0, 20.0, 30.0], 95) == 30.0

    # ties
    assert percentile([15.0, 15.0, 15.0], 50) == 15.0


def test_bucket_cancellation_and_timeout_conservation() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        criteria={"expected": "x"},
    )
    case = BenchmarkCase(case_id="c1", task_type="t1", expected_outcome=expected)

    obs_succ = BenchmarkExecutionObservation(
        agent_type="a1",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        duration_ms=10.0,
        observed_outcome=ObservedOutcome(data={"output": "x"}),
    )
    obs_fail = BenchmarkExecutionObservation(
        agent_type="a1",
        execution_status=AgentExecutionStatus.FAILED,
        duration_ms=10.0,
        observed_outcome=ObservedOutcome(data={"error": "failed"}),
        failure_category=FailureCategory.INTERNAL_ERROR,
    )
    obs_cancel = BenchmarkExecutionObservation(
        agent_type="a1",
        execution_status=AgentExecutionStatus.CANCELLED,
        duration_ms=10.0,
        observed_outcome=ObservedOutcome(data={"error": "cancelled"}),
        failure_category=FailureCategory.CANCELLED,
    )
    obs_timeout = BenchmarkExecutionObservation(
        agent_type="a1",
        execution_status=AgentExecutionStatus.TIMED_OUT,
        duration_ms=10.0,
        observed_outcome=ObservedOutcome(data={"error": "timeout"}),
        failure_category=FailureCategory.TIMEOUT,
    )

    executor = FakeBenchmarkExecutor(
        {
            ("a1", "c1", 1): obs_succ,
            ("a1", "c1", 2): obs_fail,
            ("a1", "c1", 3): obs_cancel,
            ("a1", "c1", 4): obs_timeout,
        }
    )
    suite = BenchmarkSuite(suite_id="s1", name="Suite", cases=(case,), repeat_count=4)

    runner = BenchmarkRunner()
    results, metrics = runner.run_suite(suite, ["a1"], executor)

    a1_metrics = metrics.agent_metrics["a1"]
    assert a1_metrics.execution_count == 4
    assert a1_metrics.execution_success_count == 1
    assert a1_metrics.execution_failure_count == 1
    assert a1_metrics.cancellation_count == 1
    assert a1_metrics.timeout_count == 1
    assert a1_metrics.execution_count == (
        a1_metrics.execution_success_count
        + a1_metrics.execution_failure_count
        + a1_metrics.cancellation_count
        + a1_metrics.timeout_count
    )

    task_b = a1_metrics.task_type_metrics["t1"]
    assert task_b.execution_count == 4
    assert task_b.execution_success_count == 1
    assert task_b.execution_failure_count == 1
    assert task_b.cancellation_count == 1
    assert task_b.timeout_count == 1
    assert task_b.execution_count == (
        task_b.execution_success_count
        + task_b.execution_failure_count
        + task_b.cancellation_count
        + task_b.timeout_count
    )


def test_timestamp_semantic_equality() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        criteria={"expected": "x"},
    )
    case = BenchmarkCase(case_id="c1", task_type="t1", expected_outcome=expected)
    suite = BenchmarkSuite(suite_id="s1", name="Suite", cases=(case,))

    obs = BenchmarkExecutionObservation(
        agent_type="a1",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        duration_ms=10.0,
        observed_outcome=ObservedOutcome(data={"output": "x"}),
    )
    executor = FakeBenchmarkExecutor({("a1", "c1"): obs})

    runner = BenchmarkRunner()
    t1 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    _, met1 = runner.run_suite(suite, ["a1"], executor, created_at=t1)
    _, met2 = runner.run_suite(suite, ["a1"], executor, created_at=t2)

    # Top-level aggregate metrics equality ignoring created_at timestamp difference
    assert met1 == met2


def test_reasoning_shaped_keys_rejection() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        criteria={"expected": "x"},
    )
    prohibited_reasoning_keys = [
        "chain_of_thought",
        "chain-of-thought",
        "Chain Of Thought",
        "hidden_reasoning",
        "internal_reasoning",
        "private_reasoning",
        "internal_thought",
        "hidden_prompt",
        "raw_prompt",
        "scratchpad",
    ]
    for key in prohibited_reasoning_keys:
        with pytest.raises(MalformedBenchmarkCaseError, match="prohibited"):
            BenchmarkCase(
                case_id="c1",
                task_type="t1",
                expected_outcome=expected,
                input_payload={key: "value"},
            )


def test_credential_shaped_keys_rejection() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        criteria={"expected": "x"},
    )
    prohibited_credential_keys = [
        "api_key",
        "api-key",
        "API Key",
        "apikey",
        "password",
        "credential",
        "credentials",
        "secret",
        "access_token",
        "access-token",
        "session_token",
    ]
    for key in prohibited_credential_keys:
        with pytest.raises(MalformedBenchmarkCaseError, match="prohibited"):
            BenchmarkCase(
                case_id="c1",
                task_type="t1",
                expected_outcome=expected,
                input_payload={key: "secret-value"},
            )


def test_nested_unsafe_keys_rejected_3_levels_deep() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        criteria={"expected": "x"},
    )
    # 3+ levels deep: dict -> list -> dict -> key
    nested_payload = {
        "level1": {
            "level2_list": [
                {"normal_key": 123},
                {"level3_dict": {"API-Key": "secret"}},
            ]
        }
    }
    with pytest.raises(MalformedBenchmarkCaseError, match="prohibited"):
        BenchmarkCase(
            case_id="c1",
            task_type="t1",
            expected_outcome=expected,
            input_payload=nested_payload,
        )


def test_benign_exact_keys_accepted() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        criteria={"expected": "x"},
    )
    benign_keys = [
        "secretary_task",
        "password_field_label",
        "credentials_form_schema",
        "api_key_documentation_example",
        "password_reset_ui_label",
    ]
    payload = {k: "acceptable value" for k in benign_keys}
    case = BenchmarkCase(
        case_id="c1",
        task_type="t1",
        expected_outcome=expected,
        input_payload=payload,
    )
    assert case.input_payload["secretary_task"] == "acceptable value"


def test_benchmark_suite_metadata_validation() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        criteria={"expected": "x"},
    )
    case = BenchmarkCase(case_id="c1", task_type="t1", expected_outcome=expected)

    # Suite metadata with reasoning key rejected
    with pytest.raises(MalformedBenchmarkSuiteError, match="prohibited"):
        BenchmarkSuite(
            suite_id="s1",
            name="S1",
            cases=(case,),
            metadata={"Chain-Of-Thought": "reasoning"},
        )

    # Suite metadata with credential key rejected
    with pytest.raises(MalformedBenchmarkSuiteError, match="prohibited"):
        BenchmarkSuite(
            suite_id="s1",
            name="S1",
            cases=(case,),
            metadata={"API Key": "key"},
        )

    # Suite metadata with benign keys accepted
    suite = BenchmarkSuite(
        suite_id="s1",
        name="S1",
        cases=(case,),
        metadata={"credentials_form_schema": "v1"},
    )
    assert suite.metadata["credentials_form_schema"] == "v1"


def test_legitimate_content_in_string_values_accepted() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        criteria={"expected": "x"},
    )
    # Unsafe words in string values or label values MUST be accepted
    case = BenchmarkCase(
        case_id="c1",
        task_type="t1",
        expected_outcome=expected,
        input_payload={
            "task_description": "Implement a password reset screen",
            "ui_element": {"label": "API Key"},
            "code_example": "function get_secret() { return 42; }",
        },
    )
    assert case.input_payload["task_description"] == "Implement a password reset screen"
    assert case.input_payload["ui_element"]["label"] == "API Key"
