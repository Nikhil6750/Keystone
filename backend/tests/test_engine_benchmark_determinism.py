"""Tests for Stage 7A Benchmark Engine mathematical and scheduling determinism."""

import random

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


def test_shuffled_candidate_order_produces_identical_metrics() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        criteria={"expected": "expected"},
    )
    case1 = BenchmarkCase(case_id="c1", task_type="t1", expected_outcome=expected)
    case2 = BenchmarkCase(case_id="c2", task_type="t2", expected_outcome=expected)
    suite = BenchmarkSuite(suite_id="s1", name="Suite", cases=(case1, case2))

    agents = ["agent-z", "agent-a", "agent-m"]

    responses = {}
    for a in agents:
        for c in ["c1", "c2"]:
            responses[(a, c)] = BenchmarkExecutionObservation(
                agent_type=a,
                execution_status=AgentExecutionStatus.SUCCEEDED,
                duration_ms=100.0,
                observed_outcome=ObservedOutcome(data={"output": "expected"}),
            )

    executor = FakeBenchmarkExecutor(responses)
    runner = BenchmarkRunner()

    # Order 1
    _, metrics1 = runner.run_suite(suite, ["agent-z", "agent-a", "agent-m"], executor)
    # Order 2 (shuffled)
    _, metrics2 = runner.run_suite(suite, ["agent-m", "agent-z", "agent-a"], executor)

    assert metrics1.total_results == metrics2.total_results
    assert list(metrics1.agent_metrics.keys()) == list(metrics2.agent_metrics.keys())
    assert list(metrics1.agent_metrics.keys()) == ["agent-a", "agent-m", "agent-z"]

    for agent in agents:
        m1 = metrics1.agent_metrics[agent]
        m2 = metrics2.agent_metrics[agent]
        assert m1.verified_success_count == m2.verified_success_count
        assert m1.median_latency_ms == m2.median_latency_ms


def test_10_repeated_runs_produce_identical_metrics() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        criteria={"expected": "expected"},
    )
    case = BenchmarkCase(case_id="c1", task_type="t1", expected_outcome=expected)
    suite = BenchmarkSuite(suite_id="s1", name="Suite", cases=(case,), repeat_count=3)

    agents = ["agent-1", "agent-2"]
    responses = {}
    for a in agents:
        for rep in range(1, 4):
            responses[(a, "c1", rep)] = BenchmarkExecutionObservation(
                agent_type=a,
                execution_status=AgentExecutionStatus.SUCCEEDED,
                duration_ms=50.0 * rep,
                observed_outcome=ObservedOutcome(data={"output": "expected"}),
            )

    executor = FakeBenchmarkExecutor(responses)
    runner = BenchmarkRunner()

    baseline_results, baseline_metrics = runner.run_suite(suite, agents, executor)

    for _ in range(10):
        shuffled = list(agents)
        random.shuffle(shuffled)
        res, m = runner.run_suite(suite, shuffled, executor)
        assert len(res) == len(baseline_results)
        m1 = m.agent_metrics["agent-1"].median_latency_ms
        b1 = baseline_metrics.agent_metrics["agent-1"].median_latency_ms
        assert m1 == b1
        m2 = m.agent_metrics["agent-2"].median_latency_ms
        b2 = baseline_metrics.agent_metrics["agent-2"].median_latency_ms
        assert m2 == b2
