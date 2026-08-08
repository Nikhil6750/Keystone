"""Tests for `app.engine.learning.events.LearningEvent`: valid construction,
every execution/verification scenario, and the safety/validation
invariants (status pairing, non-blank identifiers, safe repository ids)."""

from datetime import UTC, datetime

import pytest

from app.contracts.enums import AgentCapability, AgentExecutionStatus, RuntimeKind
from app.contracts.errors import FailureCategory
from app.contracts.verification import VerificationStatus
from app.engine.learning.errors import MalformedLearningEventError
from app.engine.learning.events import LearningEvent

_NOW = datetime.now(UTC)


def _event(**overrides: object) -> LearningEvent:
    base: dict[str, object] = {
        "event_id": "e1",
        "workflow_id": "wf-1",
        "agent_type": "claude_code",
        "execution_status": AgentExecutionStatus.SUCCEEDED,
        "created_at": _NOW,
    }
    base.update(overrides)
    return LearningEvent(**base)  # type: ignore[arg-type]


def test_valid_event_constructs() -> None:
    event = _event(
        step_id="step-1",
        attempt_number=1,
        runtime_kind=RuntimeKind.AGENT_CLI,
        task_type="code_generation",
        repository_id="org/repo",
        capabilities=(AgentCapability.CODE_GENERATION,),
        duration_ms=1500.0,
        verification_status=VerificationStatus.PASSED,
        cost_usd=0.05,
    )
    assert event.event_id == "e1"
    assert event.capabilities == (AgentCapability.CODE_GENERATION,)


def test_execution_success_requires_no_failure_category() -> None:
    event = _event(execution_status=AgentExecutionStatus.SUCCEEDED)
    assert event.failure_category is None


def test_execution_failure_requires_failure_category() -> None:
    with pytest.raises(MalformedLearningEventError):
        _event(execution_status=AgentExecutionStatus.FAILED, failure_category=None)
    event = _event(
        execution_status=AgentExecutionStatus.FAILED,
        failure_category=FailureCategory.PROVIDER_ERROR,
    )
    assert event.failure_category is FailureCategory.PROVIDER_ERROR


def test_cancellation_requires_cancelled_failure_category() -> None:
    event = _event(
        execution_status=AgentExecutionStatus.CANCELLED, failure_category=FailureCategory.CANCELLED
    )
    assert event.execution_status is AgentExecutionStatus.CANCELLED

    with pytest.raises(MalformedLearningEventError):
        _event(
            execution_status=AgentExecutionStatus.CANCELLED,
            failure_category=FailureCategory.PROVIDER_ERROR,
        )


def test_timed_out_requires_timeout_failure_category() -> None:
    event = _event(
        execution_status=AgentExecutionStatus.TIMED_OUT, failure_category=FailureCategory.TIMEOUT
    )
    assert event.execution_status is AgentExecutionStatus.TIMED_OUT

    with pytest.raises(MalformedLearningEventError):
        _event(
            execution_status=AgentExecutionStatus.TIMED_OUT,
            failure_category=FailureCategory.PROVIDER_ERROR,
        )


def test_retry_is_expressed_purely_via_attempt_number() -> None:
    retry_event = _event(attempt_number=2)
    assert retry_event.attempt_number == 2
    first_attempt = _event(attempt_number=1)
    assert first_attempt.attempt_number == 1


def test_attempt_number_must_be_at_least_one() -> None:
    with pytest.raises(MalformedLearningEventError):
        _event(attempt_number=0)


def test_verification_pass_recorded() -> None:
    event = _event(verification_status=VerificationStatus.PASSED)
    assert event.verification_status is VerificationStatus.PASSED


def test_verification_fail_recorded_alongside_execution_success() -> None:
    """Execution succeeded but verification failed -- both facts coexist on
    one event without contradiction."""
    event = _event(
        execution_status=AgentExecutionStatus.SUCCEEDED,
        verification_status=VerificationStatus.FAILED,
    )
    assert event.execution_status is AgentExecutionStatus.SUCCEEDED
    assert event.verification_status is VerificationStatus.FAILED


def test_verification_inconclusive_recorded() -> None:
    event = _event(verification_status=VerificationStatus.INCONCLUSIVE)
    assert event.verification_status is VerificationStatus.INCONCLUSIVE


def test_human_review_required_recorded() -> None:
    event = _event(verification_status=VerificationStatus.REQUIRES_HUMAN_REVIEW)
    assert event.verification_status is VerificationStatus.REQUIRES_HUMAN_REVIEW


def test_verification_absent_by_default() -> None:
    event = _event()
    assert event.verification_status is None


# --- validation / malformed input -------------------------------------------------


@pytest.mark.parametrize("field_name", ["event_id", "workflow_id", "agent_type"])
def test_blank_required_identifiers_are_rejected(field_name: str) -> None:
    with pytest.raises(MalformedLearningEventError):
        _event(**{field_name: "   "})


def test_blank_optional_step_id_is_rejected_if_provided() -> None:
    with pytest.raises(MalformedLearningEventError):
        _event(step_id="  ")


def test_negative_duration_ms_is_rejected() -> None:
    with pytest.raises(MalformedLearningEventError):
        _event(duration_ms=-1.0)


def test_non_finite_duration_ms_is_rejected() -> None:
    with pytest.raises(MalformedLearningEventError):
        _event(duration_ms=float("inf"))
    with pytest.raises(MalformedLearningEventError):
        _event(duration_ms=float("nan"))


def test_negative_cost_usd_is_rejected() -> None:
    with pytest.raises(MalformedLearningEventError):
        _event(cost_usd=-0.01)


def test_non_finite_cost_usd_is_rejected() -> None:
    with pytest.raises(MalformedLearningEventError):
        _event(cost_usd=float("nan"))


def test_zero_duration_and_cost_are_accepted() -> None:
    event = _event(duration_ms=0.0, cost_usd=0.0)
    assert event.duration_ms == 0.0
    assert event.cost_usd == 0.0


# --- repository_id safety --------------------------------------------------------------


@pytest.mark.parametrize(
    "unsafe_repository_id",
    [
        "/etc/passwd",
        "\\\\server\\share",
        "C:\\Users\\dev\\repo",
        "c:/Users/dev/repo",
        "../../etc/passwd",
        "org/../secrets",
    ],
)
def test_absolute_or_traversal_repository_id_is_rejected(unsafe_repository_id: str) -> None:
    with pytest.raises(MalformedLearningEventError):
        _event(repository_id=unsafe_repository_id)


@pytest.mark.parametrize("safe_repository_id", ["org/repo", "repo-slug", "a1b2c3d4"])
def test_safe_repository_id_is_accepted(safe_repository_id: str) -> None:
    event = _event(repository_id=safe_repository_id)
    assert event.repository_id == safe_repository_id
