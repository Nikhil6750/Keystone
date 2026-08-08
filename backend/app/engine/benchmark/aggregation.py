"""Pure, deterministic aggregation of benchmark execution results.

Calculates execution counts, Stage 4E verified success rates, nearest-rank
percentile latencies (p50/p95), cost evidence metrics, and per-task/per-case
breakdowns.
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from app.contracts.enums import AgentExecutionStatus
from app.contracts.verification import VerificationStatus
from app.engine.benchmark.models import BenchmarkExecutionResult


def percentile(sorted_ascending_values: list[float], target_percentile: float) -> float:
    """Nearest-rank percentile over an already-ascending-sorted list.

    Formula: `rank = ceil(target_percentile / 100 * n)`, clamped to `[1, n]`.
    Returns 0-based `(rank - 1)` index value. Shared with Stage 5A.
    """
    n = len(sorted_ascending_values)
    rank = math.ceil((target_percentile / 100.0) * n)
    rank = max(1, min(n, rank))
    return sorted_ascending_values[rank - 1]


@dataclass(frozen=True)
class BenchmarkBucketMetrics:
    """Summary metrics for one task type or case subset."""

    execution_count: int
    execution_success_count: int
    execution_failure_count: int
    cancellation_count: int
    timeout_count: int
    verification_sample_count: int
    verified_success_count: int
    verification_failure_count: int
    verified_success_rate: float | None
    median_latency_ms: float | None


@dataclass(frozen=True)
class BenchmarkAgentMetrics:
    """Complete, aggregate metrics for one candidate agent type across a benchmark run."""

    agent_type: str
    execution_count: int
    execution_success_count: int
    execution_failure_count: int
    cancellation_count: int
    timeout_count: int
    verification_sample_count: int
    verified_success_count: int
    verification_failure_count: int
    verification_inconclusive_count: int
    human_review_count: int
    verified_success_rate: float | None
    median_latency_ms: float | None
    p95_latency_ms: float | None
    known_cost_sample_count: int
    known_cost_usd_average: float | None
    known_cost_usd_total: float | None
    failure_categories: dict[str, int] = field(default_factory=dict)
    task_type_metrics: dict[str, BenchmarkBucketMetrics] = field(default_factory=dict)
    case_metrics: dict[str, BenchmarkBucketMetrics] = field(default_factory=dict)


@dataclass(frozen=True)
class BenchmarkAggregateMetrics:
    """Top-level aggregate benchmark run summary across all candidate agents.

    `created_at` is excluded from dataclass comparison (`compare=False`) so operational
    timestamps do not affect semantic result equality.
    """

    suite_id: str
    total_results: int
    agent_metrics: dict[str, BenchmarkAgentMetrics] = field(default_factory=dict)
    created_at: datetime | None = field(default=None, compare=False)


def _calculate_bucket_metrics(results: list[BenchmarkExecutionResult]) -> BenchmarkBucketMetrics:
    execution_count = len(results)
    exec_success = sum(
        1 for r in results if r.execution_status is AgentExecutionStatus.SUCCEEDED
    )
    exec_failure = sum(
        1 for r in results if r.execution_status is AgentExecutionStatus.FAILED
    )
    cancellation_count = sum(
        1 for r in results if r.execution_status is AgentExecutionStatus.CANCELLED
    )
    timeout_count = sum(
        1 for r in results if r.execution_status is AgentExecutionStatus.TIMED_OUT
    )

    verified_success = sum(
        1
        for r in results
        if r.execution_status is AgentExecutionStatus.SUCCEEDED
        and r.verification_status is VerificationStatus.PASSED
    )
    verification_failure = sum(
        1 for r in results if r.verification_status is VerificationStatus.FAILED
    )
    ver_inconclusive = sum(
        1 for r in results if r.verification_status is VerificationStatus.INCONCLUSIVE
    )
    ver_human_review = sum(
        1 for r in results if r.verification_status is VerificationStatus.REQUIRES_HUMAN_REVIEW
    )

    sample_count = (
        verified_success + verification_failure + ver_inconclusive + ver_human_review
    )
    verified_success_rate = (verified_success / sample_count) if sample_count > 0 else None

    durations = sorted(r.duration_ms for r in results if r.duration_ms is not None)
    median_latency_ms = percentile(durations, 50) if durations else None

    return BenchmarkBucketMetrics(
        execution_count=execution_count,
        execution_success_count=exec_success,
        execution_failure_count=exec_failure,
        cancellation_count=cancellation_count,
        timeout_count=timeout_count,
        verification_sample_count=sample_count,
        verified_success_count=verified_success,
        verification_failure_count=verification_failure,
        verified_success_rate=verified_success_rate,
        median_latency_ms=median_latency_ms,
    )


def _aggregate_agent_results(
    agent_type: str, results: list[BenchmarkExecutionResult]
) -> BenchmarkAgentMetrics:
    execution_count = len(results)
    exec_success = sum(
        1 for r in results if r.execution_status is AgentExecutionStatus.SUCCEEDED
    )
    exec_failure = sum(
        1 for r in results if r.execution_status is AgentExecutionStatus.FAILED
    )
    cancellation_count = sum(
        1 for r in results if r.execution_status is AgentExecutionStatus.CANCELLED
    )
    timeout_count = sum(
        1 for r in results if r.execution_status is AgentExecutionStatus.TIMED_OUT
    )

    verified_success = sum(
        1
        for r in results
        if r.execution_status is AgentExecutionStatus.SUCCEEDED
        and r.verification_status is VerificationStatus.PASSED
    )
    verification_failure = sum(
        1 for r in results if r.verification_status is VerificationStatus.FAILED
    )
    ver_inconclusive = sum(
        1 for r in results if r.verification_status is VerificationStatus.INCONCLUSIVE
    )
    ver_human_review = sum(
        1 for r in results if r.verification_status is VerificationStatus.REQUIRES_HUMAN_REVIEW
    )

    sample_count = (
        verified_success + verification_failure + ver_inconclusive + ver_human_review
    )
    verified_success_rate = (verified_success / sample_count) if sample_count > 0 else None

    durations = sorted(r.duration_ms for r in results if r.duration_ms is not None)
    median_latency_ms = percentile(durations, 50) if durations else None
    p95_latency_ms = percentile(durations, 95) if durations else None

    known_costs = [r.cost_usd for r in results if r.cost_usd is not None]
    known_cost_sample_count = len(known_costs)
    if known_costs:
        total_val = float(sum(known_costs))
        known_cost_usd_total: float | None = total_val
        known_cost_usd_average: float | None = total_val / known_cost_sample_count
    else:
        known_cost_usd_total = None
        known_cost_usd_average = None

    failure_categories: dict[str, int] = {}
    for r in results:
        if r.failure_category is not None:
            key = r.failure_category.value
            failure_categories[key] = failure_categories.get(key, 0) + 1

    by_task: dict[str, list[BenchmarkExecutionResult]] = {}
    by_case: dict[str, list[BenchmarkExecutionResult]] = {}
    for r in results:
        by_task.setdefault(r.task_type, []).append(r)
        by_case.setdefault(r.case_id, []).append(r)

    task_type_metrics = {
        task: _calculate_bucket_metrics(task_results)
        for task, task_results in sorted(by_task.items())
    }
    case_metrics = {
        case: _calculate_bucket_metrics(case_results)
        for case, case_results in sorted(by_case.items())
    }

    return BenchmarkAgentMetrics(
        agent_type=agent_type,
        execution_count=execution_count,
        execution_success_count=exec_success,
        execution_failure_count=exec_failure,
        cancellation_count=cancellation_count,
        timeout_count=timeout_count,
        verification_sample_count=sample_count,
        verified_success_count=verified_success,
        verification_failure_count=verification_failure,
        verification_inconclusive_count=ver_inconclusive,
        human_review_count=ver_human_review,
        verified_success_rate=verified_success_rate,
        median_latency_ms=median_latency_ms,
        p95_latency_ms=p95_latency_ms,
        known_cost_sample_count=known_cost_sample_count,
        known_cost_usd_average=known_cost_usd_average,
        known_cost_usd_total=known_cost_usd_total,
        failure_categories=failure_categories,
        task_type_metrics=task_type_metrics,
        case_metrics=case_metrics,
    )


def aggregate_benchmark_results(
    suite_id: str,
    results: Iterable[BenchmarkExecutionResult],
    *,
    created_at: datetime | None = None,
) -> BenchmarkAggregateMetrics:
    """Aggregate a collection of `BenchmarkExecutionResult` items into a deterministic
    `BenchmarkAggregateMetrics` instance.
    """
    result_list = list(results)
    by_agent: dict[str, list[BenchmarkExecutionResult]] = {}
    for r in result_list:
        by_agent.setdefault(r.agent_type, []).append(r)

    agent_metrics = {
        agent_type: _aggregate_agent_results(agent_type, agent_results)
        for agent_type, agent_results in sorted(by_agent.items())
    }

    return BenchmarkAggregateMetrics(
        suite_id=suite_id,
        total_results=len(result_list),
        agent_metrics=agent_metrics,
        created_at=created_at,
    )


__all__ = [
    "BenchmarkAgentMetrics",
    "BenchmarkAggregateMetrics",
    "BenchmarkBucketMetrics",
    "aggregate_benchmark_results",
    "percentile",
]
