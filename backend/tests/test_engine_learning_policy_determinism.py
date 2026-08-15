"""Tests for `app.engine.learning.policy`'s determinism: shuffled event/
passport ordering, repeated calls, and stable tie-break ranking. No
randomness, no `datetime.now()`, no external calls anywhere in the
recommendation pipeline."""

import random
from datetime import UTC, datetime

from app.contracts.enums import AgentExecutionStatus
from app.contracts.verification import VerificationStatus
from app.engine.learning.events import LearningEvent
from app.engine.learning.passport import rebuild_all_passports
from app.engine.learning.policy import LearningPolicy

_NOW = datetime.now(UTC)


def _events(
    agent_type: str, n: int, *, prefix: str, verification_status: VerificationStatus | None
) -> list[LearningEvent]:
    return [
        LearningEvent(
            event_id=f"{prefix}-{i}",
            workflow_id=f"wf-{prefix}-{i}",
            agent_type=agent_type,
            execution_status=AgentExecutionStatus.SUCCEEDED,
            created_at=_NOW,
            task_type="code_generation",
            verification_status=verification_status,
        )
        for i in range(n)
    ]


def test_shuffled_event_order_produces_identical_recommendation() -> None:
    events = (
        _events("agent_a", 8, prefix="a", verification_status=VerificationStatus.PASSED)
        + _events("agent_b", 6, prefix="b", verification_status=VerificationStatus.PASSED)
        + _events("agent_c", 5, prefix="c", verification_status=VerificationStatus.FAILED)
    )
    shuffled = list(events)
    random.Random(7).shuffle(shuffled)

    forward_passports = rebuild_all_passports(events, updated_at=_NOW)
    shuffled_passports = rebuild_all_passports(shuffled, updated_at=_NOW)

    policy = LearningPolicy()
    forward = policy.recommend(forward_passports, task_type="code_generation")
    reordered = policy.recommend(shuffled_passports, task_type="code_generation")
    assert forward == reordered


def test_shuffled_candidate_agent_types_produces_identical_recommendation() -> None:
    events = _events(
        "agent_a", 8, prefix="a", verification_status=VerificationStatus.PASSED
    ) + _events("agent_b", 6, prefix="b", verification_status=VerificationStatus.PASSED)
    passports = rebuild_all_passports(events, updated_at=_NOW)
    policy = LearningPolicy()
    forward = policy.recommend(
        passports, task_type="code_generation", candidate_agent_types=["agent_a", "agent_b"]
    )
    reordered = policy.recommend(
        passports, task_type="code_generation", candidate_agent_types=["agent_b", "agent_a"]
    )
    assert forward == reordered


def test_repeated_recommendation_twenty_times_is_stable() -> None:
    events = _events(
        "agent_a", 9, prefix="a", verification_status=VerificationStatus.PASSED
    ) + _events("agent_b", 5, prefix="b", verification_status=VerificationStatus.FAILED)
    passports = rebuild_all_passports(events, updated_at=_NOW)
    policy = LearningPolicy()
    first = policy.recommend(passports, task_type="code_generation")
    for _ in range(20):
        again = policy.recommend(passports, task_type="code_generation")
        assert again == first


def test_exact_tie_breaks_deterministically_by_agent_type() -> None:
    """Two agents with byte-for-byte identical evidence must rank in a
    fixed, documented order (`agent_type` ascending) -- never arbitrary."""
    events = _events(
        "agent_z", 8, prefix="z", verification_status=VerificationStatus.PASSED
    ) + _events("agent_a", 8, prefix="a", verification_status=VerificationStatus.PASSED)
    passports = rebuild_all_passports(events, updated_at=_NOW)
    policy = LearningPolicy()
    rec = policy.recommend(passports, task_type="code_generation")
    assert rec.agent_recommendations[0].score == rec.agent_recommendations[1].score
    assert rec.agent_recommendations[0].agent_type == "agent_a"
    assert rec.agent_recommendations[1].agent_type == "agent_z"
    assert rec.recommended_agent_types == ("agent_a", "agent_z")


def test_tie_break_is_stable_across_twenty_repeated_calls() -> None:
    events = _events(
        "agent_z", 8, prefix="z", verification_status=VerificationStatus.PASSED
    ) + _events("agent_a", 8, prefix="a", verification_status=VerificationStatus.PASSED)
    passports = rebuild_all_passports(events, updated_at=_NOW)
    policy = LearningPolicy()
    first = policy.recommend(passports, task_type="code_generation")
    for _ in range(20):
        again = policy.recommend(passports, task_type="code_generation")
        assert again.recommended_agent_types == first.recommended_agent_types


def test_no_score_agents_are_always_sorted_after_scored_agents() -> None:
    events = _events(
        "agent_scored", 8, prefix="s", verification_status=VerificationStatus.PASSED
    ) + _events("agent_low_sample", 1, prefix="l", verification_status=VerificationStatus.PASSED)
    passports = rebuild_all_passports(events, updated_at=_NOW)
    policy = LearningPolicy()
    rec = policy.recommend(passports, task_type="code_generation")
    assert rec.agent_recommendations[0].agent_type == "agent_scored"
    assert rec.agent_recommendations[0].score is not None
    assert rec.agent_recommendations[-1].agent_type == "agent_low_sample"
    assert rec.agent_recommendations[-1].score is None
