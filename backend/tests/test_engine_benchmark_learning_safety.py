"""Stage 7B SAFETY tests: no reasoning-shaped or credential-shaped field
anywhere in the module, no open `dict[str, Any]`/`Any` field for such
content to hide in, and no raw exception/path leakage."""

import dataclasses
from datetime import UTC, datetime

import pytest

from app.contracts.enums import AgentExecutionStatus, BenchmarkEvaluatorType
from app.contracts.verification import VerificationResult, VerificationStatus
from app.engine.benchmark.models import BenchmarkExecutionResult
from app.engine.benchmark_learning.adapter import convert_benchmark_result_to_learning_event
from app.engine.benchmark_learning.errors import MalformedBenchmarkLearningInputError
from app.engine.benchmark_learning.models import (
    BenchmarkLearningProvenance,
    BenchmarkLearningRecord,
    EvidenceSource,
)
from app.engine.benchmark_learning.policy import BenchmarkLearningPolicy
from app.engine.learning.events import LearningEvent

_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)

_FORBIDDEN_FIELD_NAME_SUBSTRINGS = (
    "password",
    "credential",
    "secret",
    "access_token",
    "session_token",
    "chain_of_thought",
    "reasoning",
    "internal_thought",
    "hidden_prompt",
    "raw_prompt",
    "scratchpad",
    "quality",
    "intelligence",
    "traceback",
    "stack_trace",
)

_STAGE_7B_DATACLASSES = (
    BenchmarkLearningProvenance,
    BenchmarkLearningRecord,
    BenchmarkLearningPolicy,
)


def test_no_stage7b_dataclass_has_a_forbidden_field_name() -> None:
    offenders: list[str] = []
    for cls in _STAGE_7B_DATACLASSES:
        for f in dataclasses.fields(cls):
            lowered = f.name.lower()
            if any(bad in lowered for bad in _FORBIDDEN_FIELD_NAME_SUBSTRINGS):
                offenders.append(f"{cls.__name__}.{f.name}")
    assert offenders == []


def test_no_stage7b_dataclass_has_an_open_any_or_dict_field() -> None:
    """Mirrors `LearningEvent`'s own guarantee: every field is a scalar or
    a typed enum member, never `dict[str, Any]`/`Any` -- there is
    structurally no place for reasoning content, credentials, or raw
    payloads to hide."""
    offenders: list[str] = []
    for cls in _STAGE_7B_DATACLASSES:
        for f in dataclasses.fields(cls):
            type_str = str(f.type)
            if "Any" in type_str or "dict" in type_str.lower():
                offenders.append(f"{cls.__name__}.{f.name}: {type_str}")
    assert offenders == []


def test_provenance_source_cannot_be_forged_to_a_non_benchmark_value() -> None:
    """The only way to attribute evidence to EvidenceSource.BENCHMARK is
    through this exact, validated constructor -- passing anything else for
    `source` is rejected, so provenance can never be silently mislabeled."""
    with pytest.raises(MalformedBenchmarkLearningInputError):
        BenchmarkLearningProvenance(
            event_id="e1",
            suite_id="s1",
            case_id="c1",
            agent_type="a1",
            repetition=1,
            execution_status=AgentExecutionStatus.SUCCEEDED,
            verification_status=VerificationStatus.PASSED,
            source=EvidenceSource.PRODUCTION,
        )


def test_record_rejects_mismatched_event_and_provenance_identity() -> None:
    """Defense-in-depth: a `BenchmarkLearningRecord` hand-constructed with
    an `event`/`provenance` pair that don't actually describe the same
    observation must be rejected, not silently accepted."""
    event = LearningEvent(
        event_id="benchmark::s1::c1::a1::rep1",
        workflow_id="benchmark::s1",
        agent_type="a1",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        created_at=_CREATED_AT,
        verification_status=VerificationStatus.PASSED,
    )
    mismatched_provenance = BenchmarkLearningProvenance(
        event_id="benchmark::s1::c2::a1::rep1",  # different case_id -> different identity
        suite_id="s1",
        case_id="c2",
        agent_type="a1",
        repetition=1,
        execution_status=AgentExecutionStatus.SUCCEEDED,
        verification_status=VerificationStatus.PASSED,
    )
    with pytest.raises(MalformedBenchmarkLearningInputError):
        BenchmarkLearningRecord(event=event, provenance=mismatched_provenance)


def test_converted_event_never_leaks_verification_result_internal_details_via_new_fields() -> None:
    """The Stage 7B conversion only copies typed, already-safety-checked
    scalar fields -- it never introduces a new free-text field that could
    carry a raw exception message, traceback, or absolute path."""
    verification_result = VerificationResult(
        verification_id="ver-1",
        workflow_id="bm-s1",
        step_id="c1",
        status=VerificationStatus.FAILED,
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        failure_reason="Traceback (most recent call last): secret leak /home/user/.env",
        created_at=_CREATED_AT,
    )
    result = BenchmarkExecutionResult(
        suite_id="s1",
        case_id="c1",
        agent_type="a1",
        repetition=1,
        task_type="fix",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        verification_status=VerificationStatus.FAILED,
        verification_result=verification_result,
        duration_ms=10.0,
        created_at=_CREATED_AT,
    )
    record = convert_benchmark_result_to_learning_event(result)

    # LearningEvent and BenchmarkLearningProvenance carry no field that
    # could reproduce verification_result.failure_reason's raw text.
    event_values = [str(v) for v in dataclasses.asdict(record.event).values()]
    provenance_values = [str(v) for v in dataclasses.asdict(record.provenance).values()]
    for value in event_values + provenance_values:
        assert "/home/user/.env" not in value
        assert "Traceback" not in value
