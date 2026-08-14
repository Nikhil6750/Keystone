"""Tests for Stage 7A BenchmarkRunner execution across agents and repetitions."""

from datetime import UTC, datetime

import pytest

from app.contracts.enums import AgentExecutionStatus, BenchmarkEvaluatorType
from app.contracts.errors import FailureCategory
from app.contracts.planning import ExpectedOutcome
from app.engine.benchmark.errors import BenchmarkEngineError
from app.engine.benchmark.executor import FakeBenchmarkExecutor
from app.engine.benchmark.models import (
    BenchmarkCase,
    BenchmarkExecutionObservation,
    BenchmarkSuite,
)
from app.engine.benchmark.runner import BenchmarkRunner
from app.engine.verification.evaluators import ObservedOutcome


def test_runner_single_case_single_agent() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        criteria={"expected": "expected output"},
    )
    case = BenchmarkCase(
        case_id="case-1",
        task_type="text_gen",
        expected_outcome=expected,
    )
    suite = BenchmarkSuite(
        suite_id="suite-1",
        name="Single Case Suite",
        cases=(case,),
        repeat_count=1,
    )

    obs = BenchmarkExecutionObservation(
        agent_type="claude-sonnet",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        duration_ms=250.0,
        observed_outcome=ObservedOutcome(data={"output": "expected output"}),
        cost_usd=0.005,
    )
    executor = FakeBenchmarkExecutor({("claude-sonnet", "case-1"): obs})

    runner = BenchmarkRunner()
    results, metrics = runner.run_suite(
        suite, ["claude-sonnet"], executor, created_at=datetime.now(UTC)
    )

    assert len(results) == 1
    res = results[0]
    assert res.suite_id == "suite-1"
    assert res.case_id == "case-1"
    assert res.agent_type == "claude-sonnet"
    assert res.repetition == 1
    assert res.execution_status is AgentExecutionStatus.SUCCEEDED
    assert res.verification_status.name == "PASSED"

    assert metrics.total_results == 1
    agent_m = metrics.agent_metrics["claude-sonnet"]
    assert agent_m.execution_count == 1
    assert agent_m.verified_success_count == 1
    assert agent_m.verified_success_rate == 1.0


def test_runner_multiple_cases_multiple_agents_repetitions() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        criteria={"expected": "correct"},
    )
    case1 = BenchmarkCase(case_id="c1", task_type="t1", expected_outcome=expected)
    case2 = BenchmarkCase(case_id="c2", task_type="t2", expected_outcome=expected)
    suite = BenchmarkSuite(
        suite_id="suite-2",
        name="Multi Suite",
        cases=(case1, case2),
        repeat_count=2,
    )

    obs1 = BenchmarkExecutionObservation(
        agent_type="claude",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        duration_ms=100.0,
        observed_outcome=ObservedOutcome(data={"output": "correct"}),
    )
    obs2 = BenchmarkExecutionObservation(
        agent_type="codex",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        duration_ms=150.0,
        observed_outcome=ObservedOutcome(data={"output": "wrong"}),
    )

    executor = FakeBenchmarkExecutor(
        {
            ("claude", "c1"): obs1,
            ("claude", "c2"): obs1,
            ("codex", "c1"): obs2,
            ("codex", "c2"): obs2,
        }
    )

    runner = BenchmarkRunner()
    results, metrics = runner.run_suite(suite, ["codex", "claude"], executor)

    # 2 cases * 2 agents * 2 reps = 8 results
    assert len(results) == 8
    assert metrics.total_results == 8
    assert "claude" in metrics.agent_metrics
    assert "codex" in metrics.agent_metrics

    claude_m = metrics.agent_metrics["claude"]
    assert claude_m.execution_count == 4
    assert claude_m.verified_success_count == 4
    assert claude_m.verified_success_rate == 1.0

    codex_m = metrics.agent_metrics["codex"]
    assert codex_m.execution_count == 4
    assert codex_m.verified_success_count == 0
    assert codex_m.verification_failure_count == 4
    assert codex_m.verified_success_rate == 0.0


def test_runner_handles_execution_failure_timeout_and_cancel() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        criteria={"expected": "correct"},
    )
    case = BenchmarkCase(case_id="c1", task_type="t1", expected_outcome=expected)
    suite = BenchmarkSuite(suite_id="s1", name="Suite", cases=(case,))

    obs_fail = BenchmarkExecutionObservation(
        agent_type="agent-fail",
        execution_status=AgentExecutionStatus.FAILED,
        duration_ms=500.0,
        observed_outcome=ObservedOutcome(data={"error": "adapter crash"}),
        failure_category=FailureCategory.INTERNAL_ERROR,
    )
    obs_timeout = BenchmarkExecutionObservation(
        agent_type="agent-timeout",
        execution_status=AgentExecutionStatus.TIMED_OUT,
        duration_ms=5000.0,
        observed_outcome=ObservedOutcome(data={"error": "timeout"}),
        failure_category=FailureCategory.TIMEOUT,
    )
    obs_cancel = BenchmarkExecutionObservation(
        agent_type="agent-cancel",
        execution_status=AgentExecutionStatus.CANCELLED,
        duration_ms=200.0,
        observed_outcome=ObservedOutcome(data={"error": "cancelled"}),
        failure_category=FailureCategory.CANCELLED,
    )

    executor = FakeBenchmarkExecutor(
        {
            ("agent-fail", "c1"): obs_fail,
            ("agent-timeout", "c1"): obs_timeout,
            ("agent-cancel", "c1"): obs_cancel,
        }
    )

    runner = BenchmarkRunner()
    results, metrics = runner.run_suite(
        suite, ["agent-fail", "agent-timeout", "agent-cancel"], executor
    )

    assert len(results) == 3

    m_fail = metrics.agent_metrics["agent-fail"]
    assert m_fail.execution_count == 1
    assert m_fail.execution_failure_count == 1
    assert m_fail.failure_categories["internal_error"] == 1

    m_timeout = metrics.agent_metrics["agent-timeout"]
    assert m_timeout.timeout_count == 1

    m_cancel = metrics.agent_metrics["agent-cancel"]
    assert m_cancel.cancellation_count == 1


def test_empty_candidate_agents_rejected() -> None:
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        criteria={"expected": "x"},
    )
    case = BenchmarkCase(case_id="c1", task_type="t1", expected_outcome=expected)
    suite = BenchmarkSuite(suite_id="s1", name="Suite", cases=(case,))
    runner = BenchmarkRunner()
    executor = FakeBenchmarkExecutor()

    with pytest.raises(BenchmarkEngineError, match="at least one agent type"):
        runner.run_suite(suite, [], executor)
