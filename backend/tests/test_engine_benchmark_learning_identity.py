"""Stage 7B IDENTITY + BATCH tests: deterministic event identity
(including campaign/run identity), and deterministic, duplicate-free
batch conversion."""

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
_CAMPAIGN_ID = "campaign-1"
_OTHER_CAMPAIGN_ID = "campaign-2"


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


def _convert(
    result: BenchmarkExecutionResult,
    *,
    campaign_id: str = _CAMPAIGN_ID,
    created_at: datetime | None = None,
):
    return convert_benchmark_result_to_learning_event(
        result, campaign_id=campaign_id, created_at=created_at
    )


def _convert_batch(
    results: list[BenchmarkExecutionResult],
    *,
    campaign_id: str = _CAMPAIGN_ID,
    created_at: datetime | None = None,
):
    return convert_benchmark_results_to_learning_records(
        results, campaign_id=campaign_id, created_at=created_at
    )


# --- IDENTITY ---------------------------------------------------------------------------


def test_identity_is_deterministic_for_same_result() -> None:
    result = _result()
    r1 = _convert(result)
    r2 = _convert(result)
    assert r1.event.event_id == r2.event.event_id


def test_identity_same_result_converted_twice_is_identical_event() -> None:
    result = _result()
    r1 = _convert(result)
    r2 = _convert(result)
    assert r1.event == r2.event


def test_identity_differs_by_repetition() -> None:
    r1 = _convert(_result(repetition=1))
    r2 = _convert(_result(repetition=2))
    assert r1.event.event_id != r2.event.event_id


def test_identity_differs_by_agent_type() -> None:
    r1 = _convert(_result(agent_type="agent-a"))
    r2 = _convert(_result(agent_type="agent-b"))
    assert r1.event.event_id != r2.event.event_id


def test_identity_differs_by_case_id() -> None:
    r1 = _convert(_result(case_id="c1"))
    r2 = _convert(_result(case_id="c2"))
    assert r1.event.event_id != r2.event.event_id


def test_identity_differs_by_suite_id() -> None:
    r1 = _convert(_result(suite_id="s1"))
    r2 = _convert(_result(suite_id="s2"))
    assert r1.event.event_id != r2.event.event_id


def test_identity_not_derived_from_random_uuid() -> None:
    """Same identity-bearing facts, different Python object instances --
    must still converge on the same event_id (a random-UUID-based identity
    would fail this)."""
    result_a = _result(suite_id="s9", case_id="c9", agent_type="a9", repetition=3)
    result_b = _result(suite_id="s9", case_id="c9", agent_type="a9", repetition=3)
    ra = _convert(result_a)
    rb = _convert(result_b)
    assert ra.event.event_id == rb.event.event_id


def test_identity_created_at_does_not_change_semantic_identity() -> None:
    r1 = _convert(_result(), created_at=datetime(2026, 1, 1, tzinfo=UTC))
    r2 = _convert(_result(), created_at=datetime(2026, 6, 6, tzinfo=UTC))
    assert r1.event.event_id == r2.event.event_id


def test_identity_workflow_id_stable_across_repetitions_of_same_case() -> None:
    r1 = _convert(_result(repetition=1))
    r2 = _convert(_result(repetition=2))
    assert r1.event.workflow_id == r2.event.workflow_id


def test_identity_no_timestamp_or_randomness_embedded() -> None:
    """The identity is a pure string function of campaign/suite/case/agent/
    repetition -- exercised across many repeated conversions and many
    different wall-clock created_at values, always converging on the same
    event_id for the same slot."""
    result = _result()
    ids = set()
    for created_at in (
        datetime(2020, 1, 1, tzinfo=UTC),
        datetime(2026, 6, 6, 12, 30, tzinfo=UTC),
        datetime(2099, 12, 31, 23, 59, 59, tzinfo=UTC),
    ):
        for _ in range(5):
            ids.add(_convert(result, created_at=created_at).event.event_id)
    assert len(ids) == 1


# --- CAMPAIGN IDENTITY --------------------------------------------------------------------


def test_same_campaign_and_same_slot_produce_same_event_id() -> None:
    r1 = _convert(_result(), campaign_id=_CAMPAIGN_ID)
    r2 = _convert(_result(), campaign_id=_CAMPAIGN_ID)
    assert r1.event.event_id == r2.event.event_id


def test_different_campaign_same_slot_produces_different_event_id() -> None:
    """Two genuinely separate executions of the same
    suite+case+agent+repetition (e.g. a re-run a week later) must not
    collapse into the same identity just because every other fact matches."""
    result = _result()
    r1 = _convert(result, campaign_id=_CAMPAIGN_ID)
    r2 = _convert(result, campaign_id=_OTHER_CAMPAIGN_ID)
    assert r1.event.event_id != r2.event.event_id
    # every other observable fact is identical -- only campaign differs
    assert r1.event.execution_status == r2.event.execution_status
    assert r1.provenance.suite_id == r2.provenance.suite_id
    assert r1.provenance.case_id == r2.provenance.case_id
    assert r1.provenance.agent_type == r2.provenance.agent_type
    assert r1.provenance.repetition == r2.provenance.repetition
    assert r1.provenance.campaign_id != r2.provenance.campaign_id


def test_campaign_id_preserved_in_provenance() -> None:
    record = _convert(_result(), campaign_id="my-campaign-42")
    assert record.provenance.campaign_id == "my-campaign-42"


def test_reconversion_inside_same_campaign_remains_idempotent() -> None:
    results = [_result(case_id=f"c{i}") for i in range(5)]
    first = _convert_batch(results, campaign_id=_CAMPAIGN_ID)
    second = _convert_batch(results, campaign_id=_CAMPAIGN_ID)
    assert first == second
    assert [r.event.event_id for r in first] == [r.event.event_id for r in second]


# --- BATCH ------------------------------------------------------------------------------


def test_batch_converts_multiple_results() -> None:
    results = [_result(case_id=f"c{i}") for i in range(5)]
    records = _convert_batch(results)
    assert len(records) == 5


def test_batch_shuffled_input_order_produces_same_output_order() -> None:
    results = [_result(case_id=f"c{i}", repetition=i + 1) for i in range(10)]
    shuffled = list(results)
    random.Random(7).shuffle(shuffled)

    forward = _convert_batch(results)
    from_shuffled = _convert_batch(shuffled)

    forward_ids = [r.event.event_id for r in forward]
    shuffled_ids = [r.event.event_id for r in from_shuffled]
    assert forward_ids == shuffled_ids


def test_batch_deduplicates_byte_identical_duplicates() -> None:
    result = _result()
    records = _convert_batch([result, result, result])
    assert len(records) == 1


def test_batch_conflicting_content_at_same_identity_raises() -> None:
    passed = _result(verification_status=VerificationStatus.PASSED)
    failed = _result(verification_status=VerificationStatus.FAILED)
    with pytest.raises(BenchmarkLearningIdentityConflictError):
        _convert_batch([passed, failed])


def test_batch_stable_ordering_by_event_id() -> None:
    results = [
        _result(case_id="c3"),
        _result(case_id="c1"),
        _result(case_id="c2"),
    ]
    records = _convert_batch(results)
    ids = [r.event.event_id for r in records]
    assert ids == sorted(ids)


def test_batch_empty_input_produces_empty_output() -> None:
    assert _convert_batch([]) == []
