"""Maps each `BenchmarkEvaluatorType` value to its evaluator implementation.

Every member currently defined on `BenchmarkEvaluatorType`
(`app.contracts.enums`) is registered here -- inspected directly from the
real enum during development, not assumed. A test
(`test_registry_covers_every_benchmark_evaluator_type`) asserts
`set(EVALUATORS) == set(BenchmarkEvaluatorType)`, so adding a new member to
the shared enum without registering an evaluator here is caught immediately
by that test, never silently falls through to `UnsupportedEvaluatorError`
for a real workload.
"""

from app.contracts.enums import BenchmarkEvaluatorType
from app.engine.verification.errors import UnsupportedEvaluatorError
from app.engine.verification.evaluators import (
    EvaluatorFn,
    evaluate_build,
    evaluate_exact_match,
    evaluate_exit_code,
    evaluate_file_diff,
    evaluate_human_reviewed,
    evaluate_json_schema,
    evaluate_lint,
    evaluate_regex,
    evaluate_type_check,
    evaluate_unit_test,
)

EVALUATORS: dict[BenchmarkEvaluatorType, EvaluatorFn] = {
    BenchmarkEvaluatorType.EXACT_MATCH: evaluate_exact_match,
    BenchmarkEvaluatorType.JSON_SCHEMA: evaluate_json_schema,
    BenchmarkEvaluatorType.REGEX: evaluate_regex,
    BenchmarkEvaluatorType.EXIT_CODE: evaluate_exit_code,
    BenchmarkEvaluatorType.UNIT_TEST: evaluate_unit_test,
    BenchmarkEvaluatorType.BUILD: evaluate_build,
    BenchmarkEvaluatorType.LINT: evaluate_lint,
    BenchmarkEvaluatorType.TYPE_CHECK: evaluate_type_check,
    BenchmarkEvaluatorType.FILE_DIFF: evaluate_file_diff,
    BenchmarkEvaluatorType.HUMAN_REVIEWED: evaluate_human_reviewed,
}


def get_evaluator(evaluator_type: BenchmarkEvaluatorType) -> EvaluatorFn:
    """The registered evaluator for `evaluator_type`, or raises
    `UnsupportedEvaluatorError`."""
    try:
        return EVALUATORS[evaluator_type]
    except KeyError:
        raise UnsupportedEvaluatorError(evaluator_type) from None


__all__ = ["EVALUATORS", "get_evaluator"]
