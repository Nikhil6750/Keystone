"""Typed exception hierarchy for Stage 7A Benchmark Engine Core."""


class BenchmarkEngineError(ValueError):
    """Base class for typed Stage 7A benchmark engine errors."""


class MalformedBenchmarkSuiteError(BenchmarkEngineError):
    """Raised when a `BenchmarkSuite` is invalid: blank identifier, empty case
    collection, duplicate case IDs, or invalid repeat count."""


class MalformedBenchmarkCaseError(BenchmarkEngineError):
    """Raised when a `BenchmarkCase` is invalid: blank identifier, blank task_type,
    invalid timeout, unsafe repository_id, or reasoning-shaped metadata."""


class MalformedBenchmarkObservationError(BenchmarkEngineError):
    """Raised when a `BenchmarkExecutionObservation` is invalid: inconsistent
    execution status / failure category, non-finite or negative duration/cost,
    or reasoning-shaped evidence payload."""


__all__ = [
    "BenchmarkEngineError",
    "MalformedBenchmarkCaseError",
    "MalformedBenchmarkObservationError",
    "MalformedBenchmarkSuiteError",
]
