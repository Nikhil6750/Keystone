"""Stage 7B: Benchmark -> Learning Evidence Bridge.

Architecture:

    BenchmarkExecutionResult (Stage 7A)
          |
    BenchmarkLearningAdapter (this package)
          |
    BenchmarkLearningRecord (LearningEvent + BenchmarkLearningProvenance)
          |
    BenchmarkLearningPolicy  (explicit opt-in gate)
          |
    Stage 5A Learning Aggregation (unmodified, reused directly)
          |
    LearningPassport / Stage 5B LearningRecommendation (advisory only)

**Explicit and opt-in, never automatic.** Nothing in this package feeds a
production `PassportEvidenceProvider`/`Router` by itself.
`BenchmarkLearningPolicy.enabled` defaults to `False`, and even once
enabled, a caller must explicitly build a *separate* benchmark
`PassportEvidenceProvider`/pass benchmark passports into
`LearningPolicy.recommend(...)` themselves -- Stage 7B provides the bridge,
never the wiring into routing.

Does not implement: adaptive benchmark weighting (Stage 7.5), retrieval-
augmented generation, Nemotron integration, or any change to Stage 5's
aggregation formulas, Stage 4E's verification, or the Router/scorer.
"""

from app.engine.benchmark_learning.adapter import (
    build_benchmark_learning_passports,
    convert_benchmark_result_to_learning_event,
    convert_benchmark_results_to_learning_records,
)
from app.engine.benchmark_learning.errors import (
    BenchmarkLearningError,
    BenchmarkLearningIdentityConflictError,
    MalformedBenchmarkLearningInputError,
)
from app.engine.benchmark_learning.models import (
    BenchmarkLearningProvenance,
    BenchmarkLearningRecord,
    EvidenceSource,
)
from app.engine.benchmark_learning.policy import BenchmarkLearningPolicy

__all__ = [
    "BenchmarkLearningError",
    "BenchmarkLearningIdentityConflictError",
    "BenchmarkLearningPolicy",
    "BenchmarkLearningProvenance",
    "BenchmarkLearningRecord",
    "EvidenceSource",
    "MalformedBenchmarkLearningInputError",
    "build_benchmark_learning_passports",
    "convert_benchmark_result_to_learning_event",
    "convert_benchmark_results_to_learning_records",
]
