"""Tests for the explainable routing contracts."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.contracts.routing import (
    RoutingCandidateScore,
    RoutingConstraints,
    RoutingDecision,
    RoutingRequest,
)


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


def test_eligible_candidate_with_excluded_reason_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RoutingCandidateScore.model_validate(
            {
                "agent_type": "codex",
                "eligible": True,
                "excluded_reason": "circuit breaker open",
                "capability_match": True,
            }
        )


def test_ineligible_candidate_without_excluded_reason_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RoutingCandidateScore.model_validate(
            {"agent_type": "codex", "eligible": False, "capability_match": True}
        )


def test_ineligible_candidate_with_blank_excluded_reason_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RoutingCandidateScore.model_validate(
            {
                "agent_type": "codex",
                "eligible": False,
                "excluded_reason": "   ",
                "capability_match": True,
            }
        )


def test_ineligible_candidate_with_reason_is_accepted() -> None:
    candidate = RoutingCandidateScore.model_validate(
        {
            "agent_type": "codex",
            "eligible": False,
            "excluded_reason": "circuit breaker open",
            "capability_match": True,
        }
    )
    assert candidate.eligible is False
    assert candidate.excluded_reason == "circuit breaker open"


def test_manual_override_without_selected_agent_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RoutingDecision.model_validate(
            {
                "task_type": "code_review",
                "selected_agent_type": None,
                "manual_override": True,
                "explanation": "manual override requested",
                "decided_at": datetime.now(UTC),
            }
        )


def test_manual_override_with_blank_selected_agent_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RoutingDecision.model_validate(
            {
                "task_type": "code_review",
                "selected_agent_type": "   ",
                "manual_override": True,
                "explanation": "manual override requested",
                "decided_at": datetime.now(UTC),
            }
        )


def test_non_override_decision_may_have_no_selected_agent() -> None:
    decision = RoutingDecision.model_validate(
        {
            "task_type": "code_review",
            "selected_agent_type": None,
            "manual_override": False,
            "explanation": "no eligible candidates",
            "decided_at": datetime.now(UTC),
        }
    )
    assert decision.selected_agent_type is None


def test_routing_constraints_default_to_empty_and_permissive() -> None:
    constraints = RoutingConstraints()
    assert constraints.excluded_agent_types == []
    assert constraints.allow_parallel is False
    assert constraints.consensus_size is None


def test_routing_constraints_reject_blank_entries() -> None:
    with pytest.raises(ValidationError):
        RoutingConstraints.model_validate({"excluded_agent_types": ["codex", "  "]})


def test_routing_constraints_reject_duplicate_entries() -> None:
    with pytest.raises(ValidationError):
        RoutingConstraints.model_validate({"preferred_agent_types": ["codex", "codex"]})


def test_routing_constraints_reject_negative_max_cost() -> None:
    with pytest.raises(ValidationError):
        RoutingConstraints.model_validate({"max_cost_usd": -0.01})


def test_routing_constraints_accept_zero_max_cost() -> None:
    constraints = RoutingConstraints.model_validate({"max_cost_usd": 0.0})
    assert constraints.max_cost_usd == 0.0


def test_routing_constraints_reject_non_positive_max_latency() -> None:
    with pytest.raises(ValidationError):
        RoutingConstraints.model_validate({"max_latency_ms": 0})


def test_routing_constraints_reject_out_of_range_minimum_reliability() -> None:
    with pytest.raises(ValidationError):
        RoutingConstraints.model_validate({"minimum_reliability": 1.5})
    with pytest.raises(ValidationError):
        RoutingConstraints.model_validate({"minimum_reliability": -0.1})


def test_routing_constraints_accept_boundary_minimum_reliability() -> None:
    low = RoutingConstraints.model_validate({"minimum_reliability": 0.0})
    high = RoutingConstraints.model_validate({"minimum_reliability": 1.0})
    assert low.minimum_reliability == 0.0
    assert high.minimum_reliability == 1.0


def test_routing_constraints_reject_consensus_size_below_two() -> None:
    with pytest.raises(ValidationError):
        RoutingConstraints.model_validate({"allow_parallel": True, "consensus_size": 1})


def test_routing_constraints_reject_consensus_size_without_parallel() -> None:
    with pytest.raises(ValidationError):
        RoutingConstraints.model_validate({"allow_parallel": False, "consensus_size": 2})


def test_routing_constraints_accept_consensus_size_with_parallel() -> None:
    constraints = RoutingConstraints.model_validate({"allow_parallel": True, "consensus_size": 3})
    assert constraints.consensus_size == 3


def test_routing_constraints_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        RoutingConstraints.model_validate({"provider_specific_flag": "nope"})


def test_routing_request_constraints_default_to_a_typed_empty_model() -> None:
    request = RoutingRequest.model_validate({"task_type": "code_generation"})
    assert isinstance(request.constraints, RoutingConstraints)
    assert request.constraints.excluded_agent_types == []


def test_selected_agent_types_defaults_to_empty_list() -> None:
    decision = RoutingDecision.model_validate(
        {
            "task_type": "code_generation",
            "selected_agent_type": "claude_code",
            "explanation": "only eligible candidate",
            "decided_at": datetime.now(UTC),
        }
    )
    assert decision.selected_agent_types == []


def test_selected_agent_types_may_carry_a_multi_select_set() -> None:
    decision = RoutingDecision.model_validate(
        {
            "task_type": "code_generation",
            "selected_agent_type": "claude_code",
            "selected_agent_types": ["claude_code", "codex"],
            "explanation": "consensus selection",
            "decided_at": datetime.now(UTC),
        }
    )
    assert decision.selected_agent_types == ["claude_code", "codex"]


def test_selected_agent_types_must_include_the_primary() -> None:
    with pytest.raises(ValidationError):
        RoutingDecision.model_validate(
            {
                "task_type": "code_generation",
                "selected_agent_type": "claude_code",
                "selected_agent_types": ["codex", "gemini"],
                "explanation": "consensus selection",
                "decided_at": datetime.now(UTC),
            }
        )


def test_selected_agent_types_must_be_empty_when_no_primary_is_selected() -> None:
    with pytest.raises(ValidationError):
        RoutingDecision.model_validate(
            {
                "task_type": "code_generation",
                "selected_agent_type": None,
                "selected_agent_types": ["claude_code"],
                "explanation": "no eligible candidates",
                "decided_at": datetime.now(UTC),
            }
        )


def test_routing_request_accepts_nested_constraints_dict() -> None:
    request = RoutingRequest.model_validate(
        {
            "task_type": "code_generation",
            "constraints": {"excluded_agent_types": ["codex"], "max_cost_usd": 1.5},
        }
    )
    assert request.constraints.excluded_agent_types == ["codex"]
    assert request.constraints.max_cost_usd == 1.5
