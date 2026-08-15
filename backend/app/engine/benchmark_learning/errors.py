"""Typed exception hierarchy for Stage 7B Benchmark-to-Learning integration."""


class BenchmarkLearningError(ValueError):
    """Base class for typed Stage 7B benchmark-learning errors."""


class MalformedBenchmarkLearningInputError(BenchmarkLearningError):
    """Raised when a `BenchmarkExecutionResult` cannot be converted: no
    `created_at` is available (neither on the result nor supplied
    explicitly by the caller) -- Stage 7B never fabricates a timestamp via
    `datetime.now()`."""


class BenchmarkLearningIdentityConflictError(BenchmarkLearningError):
    """Raised when two `BenchmarkExecutionResult`s in the same conversion
    batch share the same deterministic identity (`suite_id`/`case_id`/
    `agent_type`/`repetition`) but carry different observable content --
    a genuine data-integrity problem, never silently resolved by picking
    one arbitrarily. A byte-identical duplicate (the expected, harmless
    case -- e.g. reconversion, or the same result object included twice)
    is deduplicated silently instead of raising."""


__all__ = [
    "BenchmarkLearningError",
    "BenchmarkLearningIdentityConflictError",
    "MalformedBenchmarkLearningInputError",
]
