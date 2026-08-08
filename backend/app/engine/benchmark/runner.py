"""BenchmarkRunner: Orchestrates objective benchmark execution.

Executes a `BenchmarkSuite` across candidate agents using a `BenchmarkExecutor`,
evaluates observed evidence via Stage 4E's `verify_one()`, records individual
`BenchmarkExecutionResult` items, and produces `BenchmarkAggregateMetrics`.

Isolation load-bearing invariant:
Benchmark evidence is purely objective and self-contained within Stage 7 --
it NEVER mutates production Stage 5 `AgentPassport`s or Stage 4B Router evidence.
"""

from collections.abc import Iterable
from datetime import UTC, datetime

from app.contracts.enums import AgentExecutionStatus
from app.contracts.errors import FailureCategory
from app.engine.benchmark.aggregation import (
    BenchmarkAggregateMetrics,
    aggregate_benchmark_results,
)
from app.engine.benchmark.errors import BenchmarkEngineError
from app.engine.benchmark.executor import BenchmarkExecutor
from app.engine.benchmark.models import (
    BenchmarkExecutionObservation,
    BenchmarkExecutionResult,
    BenchmarkSuite,
)
from app.engine.verification.evaluators import ObservedOutcome
from app.engine.verification.verifier import verify_one


class BenchmarkRunner:
    """Orchestrates benchmark runs across candidate agents.

    Stateless and deterministic. Candidate agents and suite cases are processed
    in fixed, documented order.
    """

    def run_suite(
        self,
        suite: BenchmarkSuite,
        candidate_agent_types: Iterable[str],
        executor: BenchmarkExecutor,
        *,
        created_at: datetime | None = None,
    ) -> tuple[list[BenchmarkExecutionResult], BenchmarkAggregateMetrics]:
        """Run `suite` across `candidate_agent_types` via `executor`.

        Returns `(execution_results, aggregate_metrics)`.
        """
        agent_types = sorted(set(candidate_agent_types))
        if not agent_types:
            raise BenchmarkEngineError("candidate_agent_types must contain at least one agent type")

        ver_created_at = created_at if created_at is not None else datetime.now(UTC)
        results: list[BenchmarkExecutionResult] = []

        # Outer loop: suite cases (in declared order)
        for case in suite.cases:
            # Middle loop: candidate agents (in sorted lexicographic order)
            for agent_type in agent_types:
                # Inner loop: repetitions (1 to repeat_count)
                for rep in range(1, suite.repeat_count + 1):
                    try:
                        obs = executor.execute(
                            agent_type=agent_type,
                            case=case,
                            repetition=rep,
                        )
                    except Exception:
                        # Wrap raw executor exceptions into a clean, safe failed observation
                        # without leaking raw tracebacks, credentials, or private machine details.
                        obs = BenchmarkExecutionObservation(
                            agent_type=agent_type,
                            execution_status=AgentExecutionStatus.FAILED,
                            duration_ms=0.0,
                            observed_outcome=ObservedOutcome(
                                data={"error": "Benchmark executor raised an unhandled exception"}
                            ),
                            failure_category=FailureCategory.INTERNAL_ERROR,
                        )

                    # Reuses Stage 4E verifier 100%
                    ver_result = verify_one(
                        expected=case.expected_outcome,
                        observed=obs.observed_outcome,
                        verification_id=f"ver-{suite.suite_id}-{case.case_id}-{agent_type}-r{rep}",
                        workflow_id=f"bm-{suite.suite_id}",
                        step_id=case.case_id,
                        created_at=ver_created_at,
                    )

                    result = BenchmarkExecutionResult(
                        suite_id=suite.suite_id,
                        case_id=case.case_id,
                        agent_type=agent_type,
                        repetition=rep,
                        task_type=case.task_type,
                        repository_id=case.repository_id,
                        execution_status=obs.execution_status,
                        verification_status=ver_result.status,
                        verification_result=ver_result,
                        duration_ms=obs.duration_ms,
                        failure_category=obs.failure_category,
                        cost_usd=obs.cost_usd,
                        created_at=ver_created_at,
                    )
                    results.append(result)

        metrics = aggregate_benchmark_results(
            suite_id=suite.suite_id,
            results=results,
            created_at=created_at,
        )

        return results, metrics


__all__ = ["BenchmarkRunner"]
