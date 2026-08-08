"""Tests proving Stage 7A 100% reuses Stage 4E verification evaluators."""

from app.contracts.enums import AgentExecutionStatus, BenchmarkEvaluatorType
from app.contracts.planning import ExpectedOutcome
from app.engine.benchmark.executor import FakeBenchmarkExecutor
from app.engine.benchmark.models import (
    BenchmarkCase,
    BenchmarkExecutionObservation,
    BenchmarkSuite,
)
from app.engine.benchmark.runner import BenchmarkRunner
from app.engine.verification.evaluators import ObservedOutcome


def test_stage4e_reuse_exact_match() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        criteria={"expected": "hello"},
    )
    case = BenchmarkCase(case_id="c-exact", task_type="gen", expected_outcome=expected)
    suite = BenchmarkSuite(suite_id="s-exact", name="Exact Suite", cases=(case,))

    obs_pass = BenchmarkExecutionObservation(
        agent_type="a1",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        duration_ms=10.0,
        observed_outcome=ObservedOutcome(data={"output": "hello"}),
    )
    obs_fail = BenchmarkExecutionObservation(
        agent_type="a2",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        duration_ms=10.0,
        observed_outcome=ObservedOutcome(data={"output": "world"}),
    )
    executor = FakeBenchmarkExecutor({("a1", "c-exact"): obs_pass, ("a2", "c-exact"): obs_fail})

    runner = BenchmarkRunner()
    results, metrics = runner.run_suite(suite, ["a1", "a2"], executor)

    assert metrics.agent_metrics["a1"].verified_success_count == 1
    assert metrics.agent_metrics["a2"].verification_failure_count == 1


def test_stage4e_reuse_json_schema() -> None:
    schema = {
        "type": "object",
        "properties": {"status": {"type": "string"}},
        "required": ["status"],
    }
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.JSON_SCHEMA,
        criteria={"schema": schema},
    )
    case = BenchmarkCase(case_id="c-schema", task_type="json", expected_outcome=expected)
    suite = BenchmarkSuite(suite_id="s-schema", name="Schema Suite", cases=(case,))

    obs_pass = BenchmarkExecutionObservation(
        agent_type="a1",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        duration_ms=10.0,
        observed_outcome=ObservedOutcome(data={"output": {"status": "ok"}}),
    )
    obs_fail = BenchmarkExecutionObservation(
        agent_type="a2",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        duration_ms=10.0,
        observed_outcome=ObservedOutcome(data={"output": {"wrong_key": 123}}),
    )
    executor = FakeBenchmarkExecutor({("a1", "c-schema"): obs_pass, ("a2", "c-schema"): obs_fail})

    runner = BenchmarkRunner()
    results, metrics = runner.run_suite(suite, ["a1", "a2"], executor)

    assert metrics.agent_metrics["a1"].verified_success_count == 1
    assert metrics.agent_metrics["a2"].verification_failure_count == 1


def test_stage4e_reuse_regex() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.REGEX,
        criteria={"pattern": r"^v\d+\.\d+\.\d+$"},
    )
    case = BenchmarkCase(case_id="c-regex", task_type="ver", expected_outcome=expected)
    suite = BenchmarkSuite(suite_id="s-regex", name="Regex Suite", cases=(case,))

    obs_pass = BenchmarkExecutionObservation(
        agent_type="a1",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        duration_ms=10.0,
        observed_outcome=ObservedOutcome(data={"output": "v1.2.3"}),
    )
    obs_fail = BenchmarkExecutionObservation(
        agent_type="a2",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        duration_ms=10.0,
        observed_outcome=ObservedOutcome(data={"output": "version-1"}),
    )
    executor = FakeBenchmarkExecutor({("a1", "c-regex"): obs_pass, ("a2", "c-regex"): obs_fail})

    runner = BenchmarkRunner()
    results, metrics = runner.run_suite(suite, ["a1", "a2"], executor)

    assert metrics.agent_metrics["a1"].verified_success_count == 1
    assert metrics.agent_metrics["a2"].verification_failure_count == 1


def test_stage4e_reuse_exit_code() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXIT_CODE,
        criteria={"expected_exit_code": 0},
    )
    case = BenchmarkCase(case_id="c-exit", task_type="cmd", expected_outcome=expected)
    suite = BenchmarkSuite(suite_id="s-exit", name="Exit Suite", cases=(case,))

    obs_pass = BenchmarkExecutionObservation(
        agent_type="a1",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        duration_ms=10.0,
        observed_outcome=ObservedOutcome(data={"exit_code": 0}),
    )
    obs_fail = BenchmarkExecutionObservation(
        agent_type="a2",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        duration_ms=10.0,
        observed_outcome=ObservedOutcome(data={"exit_code": 1}),
    )
    executor = FakeBenchmarkExecutor({("a1", "c-exit"): obs_pass, ("a2", "c-exit"): obs_fail})

    runner = BenchmarkRunner()
    results, metrics = runner.run_suite(suite, ["a1", "a2"], executor)

    assert metrics.agent_metrics["a1"].verified_success_count == 1
    assert metrics.agent_metrics["a2"].verification_failure_count == 1


def test_stage4e_reuse_unit_test() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.UNIT_TEST,
        criteria={"min_tests": 1},
    )
    case = BenchmarkCase(case_id="c-ut", task_type="test", expected_outcome=expected)
    suite = BenchmarkSuite(suite_id="s-ut", name="UT Suite", cases=(case,))

    obs_pass = BenchmarkExecutionObservation(
        agent_type="a1",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        duration_ms=10.0,
        observed_outcome=ObservedOutcome(
            data={"exit_code": 0, "tests_total": 5, "tests_failed": 0}
        ),
    )
    obs_fail = BenchmarkExecutionObservation(
        agent_type="a2",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        duration_ms=10.0,
        observed_outcome=ObservedOutcome(
            data={"exit_code": 1, "tests_total": 5, "tests_failed": 2}
        ),
    )
    executor = FakeBenchmarkExecutor({("a1", "c-ut"): obs_pass, ("a2", "c-ut"): obs_fail})

    runner = BenchmarkRunner()
    results, metrics = runner.run_suite(suite, ["a1", "a2"], executor)

    assert metrics.agent_metrics["a1"].verified_success_count == 1
    assert metrics.agent_metrics["a2"].verification_failure_count == 1


def test_stage4e_reuse_file_diff() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.FILE_DIFF,
        criteria={"expected_diff": "diff --git a/f.txt b/f.txt\n+line"},
    )
    case = BenchmarkCase(case_id="c-diff", task_type="diff", expected_outcome=expected)
    suite = BenchmarkSuite(suite_id="s-diff", name="Diff Suite", cases=(case,))

    obs_pass = BenchmarkExecutionObservation(
        agent_type="a1",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        duration_ms=10.0,
        observed_outcome=ObservedOutcome(data={"diff": "diff --git a/f.txt b/f.txt\n+line"}),
    )
    obs_fail = BenchmarkExecutionObservation(
        agent_type="a2",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        duration_ms=10.0,
        observed_outcome=ObservedOutcome(data={"diff": "wrong diff"}),
    )
    executor = FakeBenchmarkExecutor({("a1", "c-diff"): obs_pass, ("a2", "c-diff"): obs_fail})

    runner = BenchmarkRunner()
    results, metrics = runner.run_suite(suite, ["a1", "a2"], executor)

    assert metrics.agent_metrics["a1"].verified_success_count == 1
    assert metrics.agent_metrics["a2"].verification_failure_count == 1
