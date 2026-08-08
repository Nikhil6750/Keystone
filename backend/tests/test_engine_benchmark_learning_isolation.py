"""Stage 7B ISOLATION + COLD START tests: benchmark evidence never
silently reaches production `PassportEvidenceProvider`/`Router`, and
benchmark-only evidence is still useful (as clearly-labeled advisory
evidence) when there is no production history at all."""

from datetime import UTC, datetime

from app.contracts.enums import AgentExecutionStatus, BenchmarkEvaluatorType
from app.contracts.verification import VerificationResult, VerificationStatus
from app.engine.benchmark.models import BenchmarkExecutionResult
from app.engine.benchmark_learning.adapter import (
    build_benchmark_learning_passports,
    convert_benchmark_results_to_learning_records,
)
from app.engine.benchmark_learning.models import EvidenceSource
from app.engine.benchmark_learning.policy import BenchmarkLearningPolicy
from app.engine.learning.events import LearningEvent
from app.engine.learning.evidence import PassportEvidenceProvider, build_passport_evidence_provider
from app.engine.routing.evidence import NullEvidenceProvider
from app.engine.routing.router import Router

_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _verification_result(status: VerificationStatus) -> VerificationResult:
    return VerificationResult(
        verification_id="ver-1",
        workflow_id="bm-s1",
        step_id="c1",
        status=status,
        evaluator_type=BenchmarkEvaluatorType.EXACT_MATCH,
        created_at=_CREATED_AT,
    )


def _benchmark_result(
    *, agent_type: str = "shared-agent", repetition: int = 1
) -> BenchmarkExecutionResult:
    return BenchmarkExecutionResult(
        suite_id="s1",
        case_id="c1",
        agent_type=agent_type,
        repetition=repetition,
        task_type="fix",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        verification_status=VerificationStatus.PASSED,
        verification_result=_verification_result(VerificationStatus.PASSED),
        duration_ms=100.0,
        created_at=_CREATED_AT,
    )


def _production_event(agent_type: str = "shared-agent") -> LearningEvent:
    return LearningEvent(
        event_id="prod-1",
        workflow_id="wf-1",
        agent_type=agent_type,
        execution_status=AgentExecutionStatus.SUCCEEDED,
        created_at=_CREATED_AT,
        task_type="fix",
        verification_status=VerificationStatus.FAILED,
    )


# --- ISOLATION --------------------------------------------------------------------------


def test_benchmark_conversion_does_not_touch_production_evidence_provider() -> None:
    # 1. Build production learning history / evidence provider.
    production_events = [_production_event()]
    production_provider = build_passport_evidence_provider(
        production_events, updated_at=_CREATED_AT
    )
    before = production_provider.overall_metrics("shared-agent")
    assert before is not None
    assert before.execution_count == 1

    # 2. Generate benchmark learning events completely separately.
    benchmark_results = [_benchmark_result(repetition=r) for r in range(1, 4)]
    records = convert_benchmark_results_to_learning_records(benchmark_results)
    filtered = BenchmarkLearningPolicy(enabled=True).filter_records(records)
    build_benchmark_learning_passports(filtered, updated_at=_CREATED_AT)

    # 3. Confirm production provider output is byte-for-byte unchanged.
    after = production_provider.overall_metrics("shared-agent")
    assert after == before
    assert after.execution_count == 1  # not 4 -- benchmark events never merged in


def test_benchmark_evidence_never_enters_a_provider_unless_explicitly_supplied() -> None:
    """Building a benchmark passport never mutates or auto-registers with
    any pre-existing `PassportEvidenceProvider` -- it only produces a new,
    separate dict a caller must explicitly choose to use."""
    production_provider = PassportEvidenceProvider(passports={})
    assert production_provider.overall_metrics("shared-agent") is None

    benchmark_results = [_benchmark_result(repetition=1)]
    records = convert_benchmark_results_to_learning_records(benchmark_results)
    filtered = BenchmarkLearningPolicy(enabled=True).filter_records(records)
    build_benchmark_learning_passports(filtered, updated_at=_CREATED_AT)

    # The pre-existing, separately-held provider is still empty.
    assert production_provider.overall_metrics("shared-agent") is None


def test_benchmark_history_does_not_mutate_router() -> None:
    router = Router(evidence=NullEvidenceProvider())

    benchmark_results = [_benchmark_result(repetition=r) for r in range(1, 4)]
    records = convert_benchmark_results_to_learning_records(benchmark_results)
    filtered = BenchmarkLearningPolicy(enabled=True).filter_records(records)
    passports = build_benchmark_learning_passports(filtered, updated_at=_CREATED_AT)
    assert "shared-agent" in passports  # benchmark evidence was really built

    # Router was never touched, still holds its original NullEvidenceProvider.
    assert router._evidence.overall_metrics("shared-agent") is None


def test_disabled_policy_produces_no_usable_benchmark_evidence_at_all() -> None:
    benchmark_results = [_benchmark_result(repetition=r) for r in range(1, 4)]
    records = convert_benchmark_results_to_learning_records(benchmark_results)
    filtered = BenchmarkLearningPolicy(enabled=False).filter_records(records)
    assert filtered == []
    passports = build_benchmark_learning_passports(filtered, updated_at=_CREATED_AT)
    assert passports == {}


def test_explicit_opt_in_required_to_build_combined_production_router() -> None:
    """A caller who genuinely wants benchmark evidence to influence routing
    must explicitly build a *separate* PassportEvidenceProvider from
    benchmark-only events and pass it to Router themselves -- this proves
    that pathway exists and is opt-in, not automatic."""
    benchmark_results = [_benchmark_result(repetition=r) for r in range(1, 6)]
    records = convert_benchmark_results_to_learning_records(benchmark_results)
    filtered = BenchmarkLearningPolicy(enabled=True).filter_records(records)
    benchmark_events = [r.event for r in filtered]

    benchmark_only_provider = build_passport_evidence_provider(
        benchmark_events, updated_at=_CREATED_AT
    )
    explicit_router = Router(evidence=benchmark_only_provider)
    assert explicit_router._evidence.overall_metrics("shared-agent") is not None

    # A default/production Router remains completely unaffected.
    default_router = Router()
    assert default_router._evidence.overall_metrics("shared-agent") is None


# --- COLD START ---------------------------------------------------------------------------


def test_cold_start_benchmark_only_evidence_available_with_no_production_history() -> None:
    production_provider = PassportEvidenceProvider(passports={})
    assert production_provider.overall_metrics("new-agent") is None  # no production history

    benchmark_results = [
        _benchmark_result(agent_type="new-agent", repetition=r) for r in range(1, 6)
    ]
    records = convert_benchmark_results_to_learning_records(benchmark_results)
    filtered = BenchmarkLearningPolicy(enabled=True).filter_records(records)
    passports = build_benchmark_learning_passports(filtered, updated_at=_CREATED_AT)

    benchmark_passport = passports["new-agent"]
    assert benchmark_passport.passport.execution_count == 5
    assert benchmark_passport.overall_verification.verified_success_rate == 1.0

    # The provenance makes clear this is benchmark, not production, evidence.
    assert all(r.provenance.source is EvidenceSource.BENCHMARK for r in filtered)


def test_cold_start_does_not_claim_production_reliability() -> None:
    """A benchmark-only LearningPassport carries no field claiming
    production-proven reliability -- AgentPassport has no such flag, and
    Stage 7B never invents one; the only honest claim available is what
    the passport actually is: benchmark-sourced evidence, distinguishable
    via BenchmarkLearningProvenance."""
    benchmark_results = [
        _benchmark_result(agent_type="new-agent", repetition=r) for r in range(1, 6)
    ]
    records = convert_benchmark_results_to_learning_records(benchmark_results)
    filtered = BenchmarkLearningPolicy(enabled=True).filter_records(records)
    passports = build_benchmark_learning_passports(filtered, updated_at=_CREATED_AT)

    passport_fields = set(vars(passports["new-agent"].passport))
    assert not any("proven" in f or "production" in f for f in passport_fields)
    # The only way to know this evidence is benchmark-derived is via the
    # separately-held provenance records, never a field on the passport.
    assert {r.provenance.source for r in filtered} == {EvidenceSource.BENCHMARK}
