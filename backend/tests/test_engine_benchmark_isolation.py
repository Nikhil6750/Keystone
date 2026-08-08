"""Tests verifying Stage 7A benchmark isolation from production evidence."""

from app.contracts.enums import AgentExecutionStatus, BenchmarkEvaluatorType
from app.contracts.planning import ExpectedOutcome
from app.engine.benchmark.executor import FakeBenchmarkExecutor
from app.engine.benchmark.models import (
    BenchmarkCase,
    BenchmarkExecutionObservation,
    BenchmarkSuite,
)
from app.engine.benchmark.runner import BenchmarkRunner
from app.engine.learning.evidence import PassportEvidenceProvider
from app.engine.routing.router import Router
from app.engine.verification.evaluators import ObservedOutcome


def test_benchmark_does_not_mutate_passport_or_router() -> None:
    # 1. Initialize an empty PassportEvidenceProvider & Router
    evidence = PassportEvidenceProvider()
    router = Router(evidence=evidence)

    # Verify initial router state has no evidence
    assert evidence.overall_metrics("claude-sonnet") is None
    assert router is not None

    # 2. Run a benchmark suite
    expected = ExpectedOutcome(
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        criteria={"expected": "result"},
    )
    case = BenchmarkCase(case_id="c1", task_type="fix", expected_outcome=expected)
    suite = BenchmarkSuite(suite_id="s1", name="Suite", cases=(case,))

    obs = BenchmarkExecutionObservation(
        agent_type="claude-sonnet",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        duration_ms=50.0,
        observed_outcome=ObservedOutcome(data={"output": "result"}),
    )
    executor = FakeBenchmarkExecutor({("claude-sonnet", "c1"): obs})

    runner = BenchmarkRunner()
    results, metrics = runner.run_suite(suite, ["claude-sonnet"], executor)

    # 3. Assert benchmark succeeded
    assert metrics.agent_metrics["claude-sonnet"].verified_success_count == 1

    # 4. Assert production evidence provider & router remain completely untouched
    assert evidence.overall_metrics("claude-sonnet") is None
