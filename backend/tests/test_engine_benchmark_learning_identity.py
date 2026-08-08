"""Stage 7B IDENTITY + BATCH tests: deterministic event identity, and
deterministic, duplicate-free batch conversion."""

import random
from datetime import UTC, datetime

import pytest

from app.contracts.enums import AgentExecutionStatus, BenchmarkEvaluatorType
from app.contracts.verification import VerificationResult, VerificationStatus
from app.engine.benchmark.models import BenchmarkExecutionResult
from app.engine.benchmark_learning.adapter import (
    convert_benchmark_result_to_learning_event,
    convert_benchmark_results_to_learning_records,
)
from app.engine.benchmark_learning.errors import BenchmarkLearningIdentityConflictError

_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _verification_result(status: VerificationStatus) -> VerificationResult:
    return VerificationResult(
        verification_id="ver-1",
        workflow_id="bm-s1",
        step_id="c1",
        status=status,
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        failure_reason="mismatch" if status is VerificationStatus.FAILED else None,
        created_at=_CREATED_AT,
    )


def _result(
    *,
    suite_id: str = "s1",
    case_id: str = "c1",
    agent_type: str = "a1",
    repetition: int = 1,
    verification_status: VerificationStatus = VerificationStatus.PASSED,
    duration_ms: float = 100.0,
    created_at: datetime | None = _CREATED_AT,
) -> BenchmarkExecutionResult:
    return BenchmarkExecutionResult(
        suite_id=suite_id,
        case_id=case_id,
        agent_type=agent_type,
        repetition=repetition,
        task_type="fix",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        verification_status=verification_status,
        verification_result=_verification_result(verification_status),
        duration_ms=duration_ms,
        created_at=created_at,
    )


# --- IDENTITY ---------------------------------------------------------------------------


def test_identity_is_deterministic_for_same_result() -> None:
    result = _result()
    r1 = convert_benchmark_result_to_learning_event(result)
    r2 = convert_benchmark_result_to_learning_event(result)
    assert r1.event.event_id == r2.event.event_id


def test_identity_same_result_converted_twice_is_identical_event() -> None:
    result = _result()
    r1 = convert_benchmark_result_to_learning_event(result)
    r2 = convert_benchmark_result_to_learning_event(result)
    assert r1.event == r2.event


def test_identity_differs_by_repetition() -> None:
    r1 = convert_benchmark_result_to_learning_event(_result(repetition=1))
    r2 = convert_benchmark_result_to_learning_event(_result(repetition=2))
    assert r1.event.event_id != r2.event.event_id


def test_identity_differs_by_agent_type() -> None:
    r1 = convert_benchmark_result_to_learning_event(_result(agent_type="agent-a"))
    r2 = convert_benchmark_result_to_learning_event(_result(agent_type="agent-b"))
    assert r1.event.event_id != r2.event.event_id


def test_identity_differs_by_case_id() -> None:
    r1 = convert_benchmark_result_to_learning_event(_result(case_id="c1"))
    r2 = convert_benchmark_result_to_learning_event(_result(case_id="c2"))
    assert r1.event.event_id != r2.event.event_id


def test_identity_differs_by_suite_id() -> None:
    r1 = convert_benchmark_result_to_learning_event(_result(suite_id="s1"))
    r2 = convert_benchmark_result_to_learning_event(_result(suite_id="s2"))
    assert r1.event.event_id != r2.event.event_id


def test_identity_not_derived_from_random_uuid() -> None:
    """Same identity-bearing facts, different Python object instances --
    must still converge on the same event_id (a random-UUID-based identity
    would fail this)."""
    result_a = _result(suite_id="s9", case_id="c9", agent_type="a9", repetition=3)
    result_b = _result(suite_id="s9", case_id="c9", agent_type="a9", repetition=3)
    ra = convert_benchmark_result_to_learning_event(result_a)
    rb = convert_benchmark_result_to_learning_event(result_b)
    assert ra.event.event_id == rb.event.event_id


def test_identity_created_at_does_not_change_semantic_identity() -> None:
    r1 = convert_benchmark_result_to_learning_event(
        _result(), created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    r2 = convert_benchmark_result_to_learning_event(
        _result(), created_at=datetime(2026, 6, 6, tzinfo=UTC)
    )
    assert r1.event.event_id == r2.event.event_id


def test_identity_workflow_id_stable_across_repetitions_of_same_case() -> None:
    r1 = convert_benchmark_result_to_learning_event(_result(repetition=1))
    r2 = convert_benchmark_result_to_learning_event(_result(repetition=2))
    assert r1.event.workflow_id == r2.event.workflow_id


# --- BATCH ------------------------------------------------------------------------------


def test_batch_converts_multiple_results() -> None:
    results = [_result(case_id=f"c{i}") for i in range(5)]
    records = convert_benchmark_results_to_learning_records(results)
    assert len(records) == 5


def test_batch_shuffled_input_order_produces_same_output_order() -> None:
    results = [_result(case_id=f"c{i}", repetition=i + 1) for i in range(10)]
    shuffled = list(results)
    random.Random(7).shuffle(shuffled)

    forward = convert_benchmark_results_to_learning_records(results)
    from_shuffled = convert_benchmark_results_to_learning_records(shuffled)

    forward_ids = [r.event.event_id for r in forward]
    shuffled_ids = [r.event.event_id for r in from_shuffled]
    assert forward_ids == shuffled_ids


def test_batch_deduplicates_byte_identical_duplicates() -> None:
    result = _result()
    records = convert_benchmark_results_to_learning_records([result, result, result])
    assert len(records) == 1


def test_batch_conflicting_content_at_same_identity_raises() -> None:
    passed = _result(verification_status=VerificationStatus.PASSED)
    failed = _result(verification_status=VerificationStatus.FAILED)
    with pytest.raises(BenchmarkLearningIdentityConflictError):
        convert_benchmark_results_to_learning_records([passed, failed])


def test_batch_stable_ordering_by_event_id() -> None:
    results = [
        _result(case_id="c3"),
        _result(case_id="c1"),
        _result(case_id="c2"),
    ]
    records = convert_benchmark_results_to_learning_records(results)
    ids = [r.event.event_id for r in records]
    assert ids == sorted(ids)


def test_batch_empty_input_produces_empty_output() -> None:
    assert convert_benchmark_results_to_learning_records([]) == []
