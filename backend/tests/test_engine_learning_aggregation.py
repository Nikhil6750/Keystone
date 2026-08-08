"""Tests for `app.engine.learning.aggregation`: deterministic percentile
calculation, bucket construction, grouping (task type / repository /
capability), failure-category counting, and low-sample-size semantics."""

from datetime import UTC, datetime

from app.contracts.enums import AgentCapability, AgentExecutionStatus
from app.contracts.errors import FailureCategory
from app.contracts.verification import VerificationStatus
from app.engine.learning.aggregation import (
    MIN_SAMPLE_SIZE_FOR_CONFIDENCE,
    bucket_from_events,
    count_failure_categories,
    group_and_bucket,
    group_by_capability_and_bucket,
    percentile,
)
from app.engine.learning.events import LearningEvent

_NOW = datetime.now(UTC)


def _event(event_id: str, **overrides: object) -> LearningEvent:
    base: dict[str, object] = {
        "event_id": event_id,
        "workflow_id": f"wf-{event_id}",
        "agent_type": "claude_code",
        "execution_status": AgentExecutionStatus.SUCCEEDED,
        "created_at": _NOW,
    }
    base.update(overrides)
    return LearningEvent(**base)  # type: ignore[arg-type]


# --- percentile: p50 / p95, odd/even counts, ties -------------------------------------


def test_percentile_single_value_returns_itself_for_any_percentile() -> None:
    assert percentile([100.0], 50) == 100.0
    assert percentile([100.0], 95) == 100.0


def test_percentile_p50_even_count() -> None:
    assert percentile([10.0, 20.0, 30.0, 40.0], 50) == 20.0


def test_percentile_p95_even_count() -> None:
    assert percentile([10.0, 20.0, 30.0, 40.0], 95) == 40.0


def test_percentile_p50_odd_count() -> None:
    assert percentile([10.0, 20.0, 30.0], 50) == 20.0


def test_percentile_p95_odd_count() -> None:
    assert percentile([10.0, 20.0, 30.0], 95) == 30.0


def test_percentile_two_values() -> None:
    assert percentile([10.0, 20.0], 50) == 10.0
    assert percentile([10.0, 20.0], 95) == 20.0


def test_percentile_with_ties() -> None:
    assert percentile([100.0, 100.0, 100.0, 100.0], 50) == 100.0
    assert percentile([100.0, 100.0, 100.0, 100.0], 95) == 100.0


# --- bucket_from_events: empty / one / multiple ----------------------------------------


def test_bucket_from_empty_events() -> None:
    bucket = bucket_from_events([])
    assert bucket.metrics.execution_count == 0
    assert bucket.metrics.success_count == 0
    assert bucket.metrics.failure_count == 0
    assert bucket.metrics.median_latency_ms is None
    assert bucket.metrics.low_sample_size is True
    assert bucket.verification.verified_success_rate is None


def test_bucket_from_one_event() -> None:
    events = [_event("e1", duration_ms=100.0)]
    bucket = bucket_from_events(events)
    assert bucket.metrics.execution_count == 1
    assert bucket.metrics.success_count == 1
    assert bucket.metrics.median_latency_ms == 100.0
    assert bucket.metrics.low_sample_size is True


def test_bucket_low_sample_size_threshold() -> None:
    below = [_event(f"e{i}") for i in range(MIN_SAMPLE_SIZE_FOR_CONFIDENCE - 1)]
    at_threshold = [_event(f"e{i}") for i in range(MIN_SAMPLE_SIZE_FOR_CONFIDENCE)]
    assert bucket_from_events(below).metrics.low_sample_size is True
    assert bucket_from_events(at_threshold).metrics.low_sample_size is False


def test_bucket_counts_success_and_failure_separately() -> None:
    events = [
        _event("e1", execution_status=AgentExecutionStatus.SUCCEEDED),
        _event("e2", execution_status=AgentExecutionStatus.SUCCEEDED),
        _event(
            "e3",
            execution_status=AgentExecutionStatus.FAILED,
            failure_category=FailureCategory.PROVIDER_ERROR,
        ),
    ]
    bucket = bucket_from_events(events)
    assert bucket.metrics.execution_count == 3
    assert bucket.metrics.success_count == 2
    assert bucket.metrics.failure_count == 1


def test_bucket_timed_out_counts_as_failure() -> None:
    events = [
        _event(
            "e1",
            execution_status=AgentExecutionStatus.TIMED_OUT,
            failure_category=FailureCategory.TIMEOUT,
        )
    ]
    bucket = bucket_from_events(events)
    assert bucket.metrics.failure_count == 1


def test_bucket_cancelled_counts_toward_execution_but_not_success_or_failure() -> None:
    events = [
        _event(
            "e1",
            execution_status=AgentExecutionStatus.CANCELLED,
            failure_category=FailureCategory.CANCELLED,
        )
    ]
    bucket = bucket_from_events(events)
    assert bucket.metrics.execution_count == 1
    assert bucket.metrics.success_count == 0
    assert bucket.metrics.failure_count == 0


def test_bucket_latency_includes_failed_and_cancelled_durations() -> None:
    events = [
        _event("e1", execution_status=AgentExecutionStatus.SUCCEEDED, duration_ms=100.0),
        _event(
            "e2",
            execution_status=AgentExecutionStatus.FAILED,
            failure_category=FailureCategory.PROVIDER_ERROR,
            duration_ms=200.0,
        ),
        _event(
            "e3",
            execution_status=AgentExecutionStatus.CANCELLED,
            failure_category=FailureCategory.CANCELLED,
            duration_ms=300.0,
        ),
    ]
    bucket = bucket_from_events(events)
    assert bucket.metrics.median_latency_ms == 200.0


def test_bucket_is_order_independent() -> None:
    events = [
        _event("e1", duration_ms=100.0),
        _event(
            "e2",
            execution_status=AgentExecutionStatus.FAILED,
            failure_category=FailureCategory.PROVIDER_ERROR,
            duration_ms=300.0,
        ),
        _event("e3", duration_ms=200.0),
    ]
    forward = bucket_from_events(events)
    backward = bucket_from_events(list(reversed(events)))
    assert forward.metrics == backward.metrics
    assert forward.verification == backward.verification


# --- verification tallies inside a bucket -----------------------------------------------


def test_bucket_verification_metrics_tally_every_status() -> None:
    events = [
        _event("e1", verification_status=VerificationStatus.PASSED),
        _event("e2", verification_status=VerificationStatus.FAILED),
        _event("e3", verification_status=VerificationStatus.INCONCLUSIVE),
        _event("e4", verification_status=VerificationStatus.REQUIRES_HUMAN_REVIEW),
        _event("e5"),  # no verification at all
    ]
    verification = bucket_from_events(events).verification
    assert verification.verified_success_count == 1
    assert verification.verification_failure_count == 1
    assert verification.verification_inconclusive_count == 1
    assert verification.human_review_count == 1
    assert verification.verification_sample_count == 4  # the unverified event excluded
    assert verification.verified_success_rate == 0.25


# --- failure categories ------------------------------------------------------------------


def test_count_failure_categories_deterministic() -> None:
    events = [
        _event(
            "e1",
            execution_status=AgentExecutionStatus.FAILED,
            failure_category=FailureCategory.TIMEOUT,
        ),
        _event(
            "e2",
            execution_status=AgentExecutionStatus.FAILED,
            failure_category=FailureCategory.TIMEOUT,
        ),
        _event(
            "e3",
            execution_status=AgentExecutionStatus.FAILED,
            failure_category=FailureCategory.PROVIDER_ERROR,
        ),
        _event("e4"),  # no failure category
    ]
    counts = count_failure_categories(events)
    assert counts == {"timeout": 2, "provider_error": 1}


# --- grouping: task_type / repository / capability -----------------------------------------


def test_group_and_bucket_by_task_type() -> None:
    events = [
        _event("e1", task_type="code_generation"),
        _event("e2", task_type="code_generation"),
        _event("e3", task_type="code_review"),
        _event("e4", task_type=None),
    ]
    groups = group_and_bucket(events, key=lambda e: e.task_type)
    assert set(groups) == {"code_generation", "code_review"}
    assert groups["code_generation"].metrics.execution_count == 2
    assert groups["code_review"].metrics.execution_count == 1


def test_group_and_bucket_by_repository() -> None:
    events = [
        _event("e1", repository_id="org/repo-a"),
        _event("e2", repository_id="org/repo-b"),
    ]
    groups = group_and_bucket(events, key=lambda e: e.repository_id)
    assert set(groups) == {"org/repo-a", "org/repo-b"}


def test_group_by_capability_and_bucket_single_capability() -> None:
    events = [
        _event("e1", capabilities=(AgentCapability.CODE_GENERATION,)),
        _event("e2", capabilities=(AgentCapability.CODE_REVIEW,)),
    ]
    groups = group_by_capability_and_bucket(events)
    assert set(groups) == {"code_generation", "code_review"}
    assert groups["code_generation"].metrics.execution_count == 1


def test_group_by_capability_and_bucket_event_contributes_to_multiple_buckets() -> None:
    events = [
        _event(
            "e1", capabilities=(AgentCapability.CODE_GENERATION, AgentCapability.TEST_GENERATION)
        )
    ]
    groups = group_by_capability_and_bucket(events)
    assert groups["code_generation"].metrics.execution_count == 1
    assert groups["test_generation"].metrics.execution_count == 1


def test_group_by_capability_no_capabilities_contributes_to_no_bucket() -> None:
    events = [_event("e1", capabilities=())]
    groups = group_by_capability_and_bucket(events)
    assert groups == {}
