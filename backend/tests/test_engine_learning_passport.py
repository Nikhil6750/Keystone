"""Tests for `app.engine.learning.passport`: `rebuild_passport`/
`rebuild_all_passports` -- verification-aware, recomputable `AgentPassport`
construction from raw `LearningEvent`s."""

import random
from datetime import UTC, datetime

from app.contracts.enums import AgentCapability, AgentExecutionStatus
from app.contracts.errors import FailureCategory
from app.contracts.verification import VerificationStatus
from app.engine.learning.events import LearningEvent
from app.engine.learning.passport import rebuild_all_passports, rebuild_passport

_NOW = datetime.now(UTC)


def _event(event_id: str, agent_type: str = "claude_code", **overrides: object) -> LearningEvent:
    base: dict[str, object] = {
        "event_id": event_id,
        "workflow_id": f"wf-{event_id}",
        "agent_type": agent_type,
        "execution_status": AgentExecutionStatus.SUCCEEDED,
        "created_at": _NOW,
    }
    base.update(overrides)
    return LearningEvent(**base)  # type: ignore[arg-type]


# --- verification awareness (scenarios A-F) -----------------------------------------------


def test_execution_success_and_verification_pass_is_verified_success() -> None:
    events = [_event("e1", verification_status=VerificationStatus.PASSED)]
    lp = rebuild_passport(events, agent_type="claude_code", updated_at=_NOW)
    assert lp.passport.success_count == 1
    assert lp.overall_verification.verified_success_count == 1


def test_execution_success_and_verification_fail_is_execution_success_and_verified_failure() -> (
    None
):
    events = [
        _event(
            "e1",
            execution_status=AgentExecutionStatus.SUCCEEDED,
            verification_status=VerificationStatus.FAILED,
        )
    ]
    lp = rebuild_passport(events, agent_type="claude_code", updated_at=_NOW)
    assert lp.passport.success_count == 1  # execution succeeded
    assert lp.overall_verification.verified_success_count == 0  # never verified success
    assert lp.overall_verification.verification_failure_count == 1


def test_execution_failure_before_verification_has_no_verified_success() -> None:
    events = [
        _event(
            "e1",
            execution_status=AgentExecutionStatus.FAILED,
            failure_category=FailureCategory.PROVIDER_ERROR,
        )
    ]
    lp = rebuild_passport(events, agent_type="claude_code", updated_at=_NOW)
    assert lp.passport.failure_count == 1
    assert lp.overall_verification.verified_success_count == 0
    assert lp.overall_verification.verification_sample_count == 0


def test_cancellation_is_not_treated_as_ordinary_success_or_failure() -> None:
    events = [
        _event(
            "e1",
            execution_status=AgentExecutionStatus.CANCELLED,
            failure_category=FailureCategory.CANCELLED,
        )
    ]
    lp = rebuild_passport(events, agent_type="claude_code", updated_at=_NOW)
    assert lp.passport.execution_count == 1
    assert lp.passport.cancellation_count == 1
    assert lp.passport.success_count == 0
    assert lp.passport.failure_count == 0


def test_verification_absent_never_counted_as_verified_success() -> None:
    events = [_event("e1", verification_status=None)]
    lp = rebuild_passport(events, agent_type="claude_code", updated_at=_NOW)
    assert lp.overall_verification.verified_success_count == 0
    assert lp.overall_verification.verified_success_rate is None


def test_inconclusive_is_never_verified_success() -> None:
    events = [_event("e1", verification_status=VerificationStatus.INCONCLUSIVE)]
    lp = rebuild_passport(events, agent_type="claude_code", updated_at=_NOW)
    assert lp.overall_verification.verified_success_count == 0
    assert lp.overall_verification.verification_inconclusive_count == 1


def test_human_review_required_is_never_verified_success() -> None:
    events = [_event("e1", verification_status=VerificationStatus.REQUIRES_HUMAN_REVIEW)]
    lp = rebuild_passport(events, agent_type="claude_code", updated_at=_NOW)
    assert lp.overall_verification.verified_success_count == 0
    assert lp.overall_verification.human_review_count == 1


# --- top-level fields: cancellation/retry/p95/failure_categories/last_* -------------------


def test_retry_count_from_attempt_number() -> None:
    events = [_event("e1", attempt_number=1), _event("e2", attempt_number=2)]
    lp = rebuild_passport(events, agent_type="claude_code", updated_at=_NOW)
    assert lp.passport.retry_count == 1


def test_p95_latency_computed_at_overall_level() -> None:
    events = [_event(f"e{i}", duration_ms=float(i * 10)) for i in range(1, 21)]
    lp = rebuild_passport(events, agent_type="claude_code", updated_at=_NOW)
    assert lp.passport.p95_latency_ms == 190.0  # rank=ceil(0.95*20)=19 -> 19th value (10..200)


def test_last_succeeded_at_is_max_created_at_among_successes() -> None:
    earlier = _NOW.replace(year=_NOW.year - 1)
    later = _NOW
    events = [
        _event("e1", execution_status=AgentExecutionStatus.SUCCEEDED, created_at=earlier),
        _event("e2", execution_status=AgentExecutionStatus.SUCCEEDED, created_at=later),
        _event(
            "e3",
            execution_status=AgentExecutionStatus.FAILED,
            failure_category=FailureCategory.PROVIDER_ERROR,
            created_at=later,
        ),
    ]
    lp = rebuild_passport(events, agent_type="claude_code", updated_at=_NOW)
    assert lp.passport.last_succeeded_at == later


def test_last_verified_at_none_when_no_verification_occurred() -> None:
    events = [_event("e1")]
    lp = rebuild_passport(events, agent_type="claude_code", updated_at=_NOW)
    assert lp.passport.last_verified_at is None


# --- no fabricated cost --------------------------------------------------------------------


def test_no_cost_evidence_yields_none_not_zero() -> None:
    events = [_event("e1", cost_usd=None)]
    lp = rebuild_passport(events, agent_type="claude_code", updated_at=_NOW)
    assert lp.known_cost_usd_average is None
    assert lp.known_cost_sample_count == 0


def test_real_cost_evidence_is_averaged_from_known_values_only() -> None:
    events = [
        _event("e1", cost_usd=0.10),
        _event("e2", cost_usd=None),
        _event("e3", cost_usd=0.30),
    ]
    lp = rebuild_passport(events, agent_type="claude_code", updated_at=_NOW)
    assert lp.known_cost_usd_average == 0.20
    assert lp.known_cost_sample_count == 2


# --- buckets: task_type / repository / capability -------------------------------------------


def test_buckets_present_for_task_type_repository_capability() -> None:
    events = [
        _event(
            "e1",
            task_type="code_generation",
            repository_id="org/repo",
            capabilities=(AgentCapability.CODE_GENERATION,),
        )
    ]
    lp = rebuild_passport(events, agent_type="claude_code", updated_at=_NOW)
    assert "code_generation" in lp.task_type_buckets
    assert "org/repo" in lp.repository_buckets
    assert "code_generation" in lp.capability_buckets
    task_bucket_metrics = lp.task_type_buckets["code_generation"].metrics
    assert lp.passport.task_type_metrics["code_generation"] == task_bucket_metrics
    repo_bucket_metrics = lp.repository_buckets["org/repo"].metrics
    assert lp.passport.repository_metrics["org/repo"] == repo_bucket_metrics


def test_overall_bucket_never_leaks_into_task_or_repository_buckets_incorrectly() -> None:
    events = [
        _event("e1", task_type="code_generation", repository_id="org/repo-a"),
        _event("e2", task_type="code_review", repository_id="org/repo-b"),
    ]
    lp = rebuild_passport(events, agent_type="claude_code", updated_at=_NOW)
    assert lp.passport.execution_count == 2
    assert lp.task_type_buckets["code_generation"].metrics.execution_count == 1
    assert lp.task_type_buckets["code_review"].metrics.execution_count == 1


# --- recomputation: rebuild from raw events is the source of truth --------------------------


def test_rebuild_is_deterministic_given_same_events() -> None:
    events = [
        _event("e1", task_type="code_generation", verification_status=VerificationStatus.PASSED),
        _event(
            "e2",
            execution_status=AgentExecutionStatus.FAILED,
            failure_category=FailureCategory.TIMEOUT,
        ),
    ]
    first = rebuild_passport(events, agent_type="claude_code", updated_at=_NOW)
    for _ in range(20):
        again = rebuild_passport(events, agent_type="claude_code", updated_at=_NOW)
        assert again.passport == first.passport
        assert again.overall_verification == first.overall_verification
        assert again.task_type_buckets == first.task_type_buckets
        assert again.known_cost_usd_average == first.known_cost_usd_average


def test_rebuild_is_order_independent() -> None:
    events = [
        _event(
            "e1",
            task_type="a",
            duration_ms=100.0,
            verification_status=VerificationStatus.PASSED,
        ),
        _event(
            "e2",
            task_type="b",
            execution_status=AgentExecutionStatus.FAILED,
            failure_category=FailureCategory.TIMEOUT,
            duration_ms=200.0,
        ),
        _event(
            "e3",
            task_type="a",
            duration_ms=300.0,
            verification_status=VerificationStatus.FAILED,
        ),
    ]
    shuffled = list(events)
    random.Random(42).shuffle(shuffled)

    forward = rebuild_passport(events, agent_type="claude_code", updated_at=_NOW)
    reordered = rebuild_passport(shuffled, agent_type="claude_code", updated_at=_NOW)
    assert forward.passport == reordered.passport
    assert forward.overall_verification == reordered.overall_verification
    assert forward.task_type_buckets == reordered.task_type_buckets


def test_rebuild_ignores_events_for_other_agent_types() -> None:
    events = [
        _event("e1", agent_type="claude_code"),
        _event("e2", agent_type="codex"),
    ]
    lp = rebuild_passport(events, agent_type="claude_code", updated_at=_NOW)
    assert lp.passport.execution_count == 1


def test_rebuild_all_passports_groups_by_agent_type() -> None:
    events = [
        _event("e1", agent_type="claude_code"),
        _event("e2", agent_type="claude_code"),
        _event("e3", agent_type="codex"),
    ]
    passports = rebuild_all_passports(events, updated_at=_NOW)
    assert set(passports) == {"claude_code", "codex"}
    assert passports["claude_code"].passport.execution_count == 2
    assert passports["codex"].passport.execution_count == 1


def test_rebuild_empty_events_produces_empty_passport() -> None:
    lp = rebuild_passport([], agent_type="claude_code", updated_at=_NOW)
    assert lp.passport.execution_count == 0
    assert lp.passport.low_sample_size is True
    assert lp.passport.median_latency_ms is None
    assert lp.passport.p95_latency_ms is None
    assert lp.task_type_buckets == {}
    assert lp.repository_buckets == {}
    assert lp.capability_buckets == {}
