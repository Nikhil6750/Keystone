"""Tests for Stage 7A pure benchmark metrics aggregation."""

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


def test_execution_success_vs_verified_success_separation() -> None:
    """SUCCEEDED execution with FAILED verification MUST count as execution success +1
    and verified success +0 (verified failure +1)."""
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        criteria={"expected": "expected"},
    )
    case = BenchmarkCase(case_id="c1", task_type="t1", expected_outcome=expected)
    suite = BenchmarkSuite(suite_id="s1", name="Suite", cases=(case,))

    obs = BenchmarkExecutionObservation(
        agent_type="a1",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        duration_ms=100.0,
        observed_outcome=ObservedOutcome(data={"output": "wrong output"}),  # fails verification
    )
    executor = FakeBenchmarkExecutor({("a1", "c1"): obs})

    runner = BenchmarkRunner()
    results, metrics = runner.run_suite(suite, ["a1"], executor)

    agent_m = metrics.agent_metrics["a1"]
    assert agent_m.execution_count == 1
    assert agent_m.execution_success_count == 1  # transport success
    assert agent_m.verified_success_count == 0  # verification failed!
    assert agent_m.verification_failure_count == 1
    assert agent_m.verified_success_rate == 0.0


def test_percentile_latencies_and_costs() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        criteria={"expected": "correct"},
    )
    case = BenchmarkCase(case_id="c1", task_type="t1", expected_outcome=expected)
    suite = BenchmarkSuite(suite_id="s1", name="Suite", cases=(case,), repeat_count=5)

    durations = [100.0, 200.0, 300.0, 400.0, 500.0]
    responses = {}
    for rep, dur in enumerate(durations, start=1):
        responses[("a1", "c1", rep)] = BenchmarkExecutionObservation(
            agent_type="a1",
            execution_status=AgentExecutionStatus.SUCCEEDED,
            duration_ms=dur,
            observed_outcome=ObservedOutcome(data={"output": "correct"}),
            cost_usd=0.01 if rep <= 3 else None,  # only 3 runs report cost
        )

    executor = FakeBenchmarkExecutor(responses)
    runner = BenchmarkRunner()
    results, metrics = runner.run_suite(suite, ["a1"], executor)

    agent_m = metrics.agent_metrics["a1"]
    assert agent_m.execution_count == 5
    assert agent_m.median_latency_ms == 300.0  # nearest-rank p50 of [100..500]
    assert agent_m.p95_latency_ms == 500.0  # nearest-rank p95 of [100..500]

    assert agent_m.known_cost_sample_count == 3
    assert agent_m.known_cost_usd_total == 0.03
    assert agent_m.known_cost_usd_average == 0.01


def test_task_type_and_case_breakdowns() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        criteria={"expected": "correct"},
    )
    case1 = BenchmarkCase(case_id="c1", task_type="code_fix", expected_outcome=expected)
    case2 = BenchmarkCase(case_id="c2", task_type="doc_gen", expected_outcome=expected)
    suite = BenchmarkSuite(suite_id="s1", name="Suite", cases=(case1, case2))

    obs1 = BenchmarkExecutionObservation(
        agent_type="a1",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        duration_ms=100.0,
        observed_outcome=ObservedOutcome(data={"output": "correct"}),
    )
    obs2 = BenchmarkExecutionObservation(
        agent_type="a1",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        duration_ms=200.0,
        observed_outcome=ObservedOutcome(data={"output": "wrong"}),
    )
    executor = FakeBenchmarkExecutor({("a1", "c1"): obs1, ("a1", "c2"): obs2})

    runner = BenchmarkRunner()
    results, metrics = runner.run_suite(suite, ["a1"], executor)

    agent_m = metrics.agent_metrics["a1"]
    assert "code_fix" in agent_m.task_type_metrics
    assert "doc_gen" in agent_m.task_type_metrics
    assert agent_m.task_type_metrics["code_fix"].verified_success_count == 1
    assert agent_m.task_type_metrics["doc_gen"].verified_success_count == 0

    assert "c1" in agent_m.case_metrics
    assert "c2" in agent_m.case_metrics
