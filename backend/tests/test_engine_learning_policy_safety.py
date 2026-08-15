"""Cross-cutting SAFETY tests for Stage 5B: no hidden-reasoning, credential,
or subjective-quality field anywhere in the recommendation types, and the
reason-code vocabulary is closed (never free-form model text)."""

import dataclasses
from datetime import UTC, datetime

import pytest

from app.contracts.enums import AgentExecutionStatus
from app.contracts.verification import VerificationStatus
from app.engine.learning.events import LearningEvent
from app.engine.learning.passport import rebuild_all_passports
from app.engine.learning.policy import LearningPolicy
from app.engine.learning.recommendation import (
    REASON_CODES,
    AgentRecommendation,
    LearningRecommendation,
    RecommendationOutcome,
)
from app.engine.learning.scoring import RecommendationWeights

_NOW = datetime.now(UTC)

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
    "prestige",
    "brand",
)

_RECOMMENDATION_DATACLASSES = (AgentRecommendation, LearningRecommendation, RecommendationWeights)


def test_no_recommendation_dataclass_has_a_forbidden_field_name() -> None:
    offenders: list[str] = []
    for cls in _RECOMMENDATION_DATACLASSES:
        for f in dataclasses.fields(cls):
            lowered = f.name.lower()
            if any(bad in lowered for bad in _FORBIDDEN_FIELD_NAME_SUBSTRINGS):
                offenders.append(f"{cls.__name__}.{f.name}")
    assert offenders == []


def test_reason_code_vocabulary_is_closed_not_free_form() -> None:
    """An arbitrary, non-whitelisted reason code string must be rejected --
    proving reason codes are a fixed, stable vocabulary, never free-form
    model-generated text."""
    with pytest.raises(ValueError, match="unknown reason code"):
        AgentRecommendation(
            agent_type="agent_a",
            outcome=RecommendationOutcome.RECOMMEND,
            tier_used="overall",
            score=0.8,
            sample_count=10,
            verified_sample_count=10,
            verified_success_rate=0.8,
            reason_codes=("the model believes this agent is trustworthy",),
        )


def test_every_produced_reason_code_is_in_the_closed_vocabulary() -> None:
    events = [
        LearningEvent(
            event_id=f"e{i}",
            workflow_id=f"wf{i}",
            agent_type="agent_a",
            execution_status=AgentExecutionStatus.SUCCEEDED,
            created_at=_NOW,
            task_type="code_generation",
            verification_status=VerificationStatus.PASSED if i < 8 else VerificationStatus.FAILED,
            attempt_number=2 if i % 2 == 0 else 1,
        )
        for i in range(10)
    ]
    passports = rebuild_all_passports(events, updated_at=_NOW)
    rec = LearningPolicy().recommend(passports, task_type="code_generation")
    for agent_rec in rec.agent_recommendations:
        assert set(agent_rec.reason_codes).issubset(REASON_CODES)


def test_evidence_summary_is_built_from_fixed_templates_not_free_text() -> None:
    """The evidence summary always mentions the agent type and a numeric
    count/rate -- confirming it is a deterministic template fill, not
    freely generated text that could smuggle arbitrary content."""
    events = [
        LearningEvent(
            event_id=f"e{i}",
            workflow_id=f"wf{i}",
            agent_type="agent_a",
            execution_status=AgentExecutionStatus.SUCCEEDED,
            created_at=_NOW,
            task_type="code_generation",
            verification_status=VerificationStatus.PASSED,
        )
        for i in range(8)
    ]
    passports = rebuild_all_passports(events, updated_at=_NOW)
    rec = LearningPolicy().recommend(passports, task_type="code_generation")
    summary = rec.agent_recommendations[0].evidence_summary
    assert "agent_a" in summary
    assert "verified sample" in summary
    assert "%" in summary


def test_recommendation_weights_reject_out_of_range_avoid_threshold() -> None:
    with pytest.raises(ValueError, match="avoid_threshold"):
        RecommendationWeights(avoid_threshold=1.5)


def test_recommendation_weights_reject_non_unit_sum() -> None:
    with pytest.raises(ValueError, match="sum to 1.0"):
        RecommendationWeights(verified_success_weight=0.9)


def test_agent_recommendation_score_and_outcome_consistency_enforced() -> None:
    """A RECOMMEND/AVOID_IF_POSSIBLE outcome must always carry a real score;
    an INSUFFICIENT_EVIDENCE/NO_EVIDENCE outcome must never carry one."""
    with pytest.raises(ValueError):
        AgentRecommendation(
            agent_type="agent_a",
            outcome=RecommendationOutcome.RECOMMEND,
            tier_used="overall",
            score=None,
            sample_count=10,
            verified_sample_count=10,
            verified_success_rate=0.9,
        )
    with pytest.raises(ValueError):
        AgentRecommendation(
            agent_type="agent_a",
            outcome=RecommendationOutcome.NO_EVIDENCE,
            tier_used="none",
            score=0.5,
            sample_count=0,
            verified_sample_count=0,
            verified_success_rate=None,
        )
