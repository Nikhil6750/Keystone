"""Stage 7A: Objective Benchmark Engine Core.

Architecture:

    BenchmarkSuite
          ↓
    BenchmarkCases
          ↓
    BenchmarkRunner
          ↓
    Injected Agent Execution Seam (BenchmarkExecutor)
          ↓
    Observed Outcome
          ↓
    Existing Stage 4E Verification (verify_one)
          ↓
    Benchmark Execution Result
          ↓
    Aggregate Metrics

Reuses Stage 4E verification contracts and evaluators 100%.
Does not modify routing evidence, Stage 5 passports, or external LLMs.
"""

from app.engine.benchmark.aggregation import (
    BenchmarkAgentMetrics,
    BenchmarkAggregateMetrics,
    BenchmarkBucketMetrics,
    aggregate_benchmark_results,
    percentile,
)
from app.engine.benchmark.errors import (
    BenchmarkEngineError,
    MalformedBenchmarkCaseError,
    MalformedBenchmarkObservationError,
    MalformedBenchmarkSuiteError,
)
from app.engine.benchmark.executor import BenchmarkExecutor, FakeBenchmarkExecutor
from app.engine.benchmark.models import (
    MAX_BENCHMARK_REPEAT_COUNT,
    BenchmarkCase,
    BenchmarkExecutionObservation,
    BenchmarkExecutionResult,
    BenchmarkSuite,
)
from app.engine.benchmark.runner import BenchmarkRunner

__all__ = [
    "MAX_BENCHMARK_REPEAT_COUNT",
    "BenchmarkAgentMetrics",
    "BenchmarkAggregateMetrics",
    "BenchmarkBucketMetrics",
    "BenchmarkCase",
    "BenchmarkEngineError",
    "BenchmarkExecutionObservation",
    "BenchmarkExecutionResult",
    "BenchmarkExecutor",
    "BenchmarkRunner",
    "BenchmarkSuite",
    "FakeBenchmarkExecutor",
    "MalformedBenchmarkCaseError",
    "MalformedBenchmarkObservationError",
    "MalformedBenchmarkSuiteError",
    "aggregate_benchmark_results",
    "percentile",
]
