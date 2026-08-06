"""Tests for the explainable routing contracts."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.contracts.routing import RoutingCandidateScore, RoutingDecision, RoutingRequest


def test_blank_task_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RoutingRequest.model_validate({"task_type": "   "})


def test_decision_requires_a_non_blank_explanation() -> None:
    with pytest.raises(ValidationError):
        RoutingDecision.model_validate(
            {
                "task_type": "code_generation",
                "selected_agent_type": "claude_code",
                "explanation": "  ",
                "decided_at": datetime.now(UTC),
            }
        )


def test_missing_historical_data_is_not_a_perfect_score() -> None:
    candidate = RoutingCandidateScore.model_validate(
        {
            "agent_type": "codex",
            "eligible": True,
            "capability_match": True,
            "sample_size": 0,
            "low_sample_size": True,
        }
    )
    assert candidate.reliability_score is None
    assert candidate.low_sample_size is True


def test_manual_override_decision_round_trips() -> None:
    decision = RoutingDecision.model_validate(
        {
            "task_type": "code_review",
            "selected_agent_type": "claude_code",
            "manual_override": True,
            "explanation": "user manually selected claude_code",
            "decided_at": datetime.now(UTC),
        }
    )
    assert decision.manual_override is True
    assert decision.candidates == []


def test_no_candidate_decision_has_null_selected_agent() -> None:
    decision = RoutingDecision.model_validate(
        {
            "task_type": "code_review",
            "selected_agent_type": None,
            "explanation": "no eligible candidates: all circuits open",
            "decided_at": datetime.now(UTC),
        }
    )
    assert decision.selected_agent_type is None
