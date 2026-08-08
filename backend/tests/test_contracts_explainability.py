"""Tests for the Explainability contracts: `DecisionTrace`, `EvidenceItem`,
`ScoreContribution`, `ExclusionReason`, `Confidence`,
`CounterfactualCondition`, `RoutingExplanation`."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.contracts.explainability import (
    Confidence,
    CounterfactualCondition,
    DecisionTrace,
    DecisionType,
    EvidenceItem,
    ExclusionReason,
    RoutingExplanation,
    ScoreContribution,
)
from app.contracts.routing import RoutingDecision
from app.contracts.schema_export import CONTRACT_MODELS

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
)


def test_decision_trace_round_trips_through_json() -> None:
    trace = DecisionTrace(
        decision_id="d1",
        decision_type=DecisionType.ROUTING,
        subject_id="wf-1",
        summary="selected claude_code",
        evidence=[EvidenceItem(kind="success_rate", description="90% over 20 runs", value=0.9)],
        confidence=Confidence(value=0.8, basis="sample_size", sample_size=20),
        counterfactuals=[
            CounterfactualCondition(
                description="if codex's success rate exceeded 90%, it would have been selected",
                would_change_outcome_to="codex",
            )
        ],
        created_at=_NOW,
    )
    restored = DecisionTrace.model_validate_json(trace.model_dump_json())
    assert restored == trace


def test_decision_trace_rejects_blank_summary() -> None:
    with pytest.raises(ValidationError):
        DecisionTrace(
            decision_id="d1",
            decision_type=DecisionType.PLANNING,
            subject_id="wf-1",
            summary="   ",
            created_at=_NOW,
        )


@pytest.mark.parametrize("decision_type", list(DecisionType))
def test_decision_type_covers_every_documented_decision_kind(decision_type: DecisionType) -> None:
    trace = DecisionTrace(
        decision_id="d1",
        decision_type=decision_type,
        subject_id="wf-1",
        summary="x",
        created_at=_NOW,
    )
    assert trace.decision_type is decision_type


def test_confidence_value_must_be_between_zero_and_one() -> None:
    with pytest.raises(ValidationError):
        Confidence(value=1.1, basis="sample_size")
    with pytest.raises(ValidationError):
        Confidence(value=-0.01, basis="sample_size")
    Confidence(value=0.0, basis="sample_size")
    Confidence(value=1.0, basis="sample_size")


def test_confidence_rejects_blank_basis() -> None:
    with pytest.raises(ValidationError):
        Confidence(value=0.5, basis="  ")


def test_score_contribution_carries_weight_and_optional_raw_score() -> None:
    contribution = ScoreContribution(factor_name="reliability", weight=0.6)
    assert contribution.raw_score is None
    assert contribution.low_sample_size is False

    with_score = ScoreContribution(
        factor_name="reliability", raw_score=0.9, weight=0.6, weighted_contribution=0.54
    )
    assert with_score.weighted_contribution == 0.54


def test_score_contribution_rejects_blank_factor_name() -> None:
    with pytest.raises(ValidationError):
        ScoreContribution(factor_name="  ", weight=0.5)


def test_exclusion_reason_requires_all_fields_non_blank() -> None:
    with pytest.raises(ValidationError):
        ExclusionReason(candidate_id="", reason_code="x", reason_text="y")
    with pytest.raises(ValidationError):
        ExclusionReason(candidate_id="agent-1", reason_code="  ", reason_text="y")
    reason = ExclusionReason(
        candidate_id="agent-1", reason_code="circuit_breaker_open", reason_text="circuit is open"
    )
    assert reason.candidate_id == "agent-1"


def test_routing_explanation_nests_the_existing_routing_decision() -> None:
    decision = RoutingDecision(
        task_type="code_generation",
        selected_agent_type="claude_code",
        explanation="only eligible candidate",
        decided_at=_NOW,
    )
    trace = DecisionTrace(
        decision_id="d1",
        decision_type=DecisionType.ROUTING,
        subject_id="wf-1",
        summary="selected claude_code",
        created_at=_NOW,
    )
    explanation = RoutingExplanation(
        decision=decision,
        trace=trace,
        score_contributions={
            "claude_code": [ScoreContribution(factor_name="reliability", weight=1.0)]
        },
        exclusions=[
            ExclusionReason(candidate_id="codex", reason_code="unavailable", reason_text="offline")
        ],
    )
    restored = RoutingExplanation.model_validate_json(explanation.model_dump_json())
    assert restored.decision.selected_agent_type == "claude_code"
    assert restored.trace.decision_type is DecisionType.ROUTING
    assert restored.score_contributions["claude_code"][0].factor_name == "reliability"
    assert restored.exclusions[0].candidate_id == "codex"


def test_evidence_item_rejects_reasoning_shaped_dict_value() -> None:
    with pytest.raises(ValidationError):
        EvidenceItem(
            kind="model_output", description="raw output", value={"chain_of_thought": "secret"}
        )


def test_evidence_item_rejects_reasoning_shaped_key_nested_in_a_dict() -> None:
    with pytest.raises(ValidationError):
        EvidenceItem(
            kind="model_output",
            description="raw output",
            value={"details": {"chain_of_thought": "secret"}},
        )


def test_evidence_item_rejects_reasoning_shaped_key_inside_a_list() -> None:
    with pytest.raises(ValidationError):
        EvidenceItem(
            kind="model_output",
            description="raw output",
            value=[{"internal_reasoning": "secret"}],
        )


def test_evidence_item_accepts_benign_key_that_merely_mentions_reasoning() -> None:
    """`reasoning_step_count` is a plain observable count, not reasoning
    content — the safety check matches exact reserved key names, not any
    key containing the substring "reasoning"."""
    item = EvidenceItem(
        kind="model_output", description="raw output", value={"reasoning_step_count": 4}
    )
    assert item.value == {"reasoning_step_count": 4}


def test_evidence_item_accepts_plain_observable_value() -> None:
    item = EvidenceItem(kind="latency", description="median latency", value=1200.5, sample_size=15)
    assert item.value == 1200.5


def test_counterfactual_condition_round_trips_through_json() -> None:
    condition = CounterfactualCondition(
        description="if codex's success rate exceeded 90%, it would have been selected",
        would_change_outcome_to="codex",
    )
    restored = CounterfactualCondition.model_validate_json(condition.model_dump_json())
    assert restored == condition


def test_counterfactual_condition_rejects_blank_description() -> None:
    with pytest.raises(ValidationError):
        CounterfactualCondition(description="   ")


def test_counterfactual_condition_would_change_outcome_to_is_optional() -> None:
    condition = CounterfactualCondition(description="no alternative outcome was close")
    assert condition.would_change_outcome_to is None


def test_score_contribution_accepts_lower_bound_zero() -> None:
    contribution = ScoreContribution(
        factor_name="reliability", raw_score=0.0, weight=0.0, weighted_contribution=0.0
    )
    assert contribution.raw_score == 0.0
    assert contribution.weight == 0.0
    assert contribution.weighted_contribution == 0.0


def test_score_contribution_accepts_upper_bound_one() -> None:
    contribution = ScoreContribution(
        factor_name="reliability", raw_score=1.0, weight=1.0, weighted_contribution=1.0
    )
    assert contribution.raw_score == 1.0
    assert contribution.weight == 1.0
    assert contribution.weighted_contribution == 1.0


@pytest.mark.parametrize("field_name", ["raw_score", "weight", "weighted_contribution"])
def test_score_contribution_rejects_negative_values(field_name: str) -> None:
    kwargs: dict[str, object] = {"factor_name": "reliability", "weight": 0.5}
    kwargs[field_name] = -0.01
    with pytest.raises(ValidationError):
        ScoreContribution(**kwargs)


@pytest.mark.parametrize("field_name", ["raw_score", "weight", "weighted_contribution"])
def test_score_contribution_rejects_values_above_one(field_name: str) -> None:
    kwargs: dict[str, object] = {"factor_name": "reliability", "weight": 0.5}
    kwargs[field_name] = 1.01
    with pytest.raises(ValidationError):
        ScoreContribution(**kwargs)


def test_score_contribution_does_not_require_weighted_contribution_to_equal_raw_times_weight() -> (
    None
):
    """Future scoring may normalize/rescale before combining terms, so the
    contract only bounds each value to [0, 1] — it never enforces the
    arithmetic relationship between them. `0.2 * 0.5 == 0.1`, not `0.9`, and
    this must still construct without error."""
    contribution = ScoreContribution(
        factor_name="reliability", raw_score=0.2, weight=0.5, weighted_contribution=0.9
    )
    assert contribution.weighted_contribution == 0.9


def test_no_contract_model_has_a_credential_or_reasoning_shaped_field_name() -> None:
    """Static, schema-level guard alongside the runtime dict-key guard on
    EvidenceItem/VerificationEvidence: no contract model anywhere may define
    a field literally named after a credential or a model's internal
    reasoning."""
    offenders: list[str] = []
    for name, model in CONTRACT_MODELS.items():
        for field_name in model.model_fields:
            lowered = field_name.lower()
            if any(bad in lowered for bad in _FORBIDDEN_FIELD_NAME_SUBSTRINGS):
                offenders.append(f"{name}.{field_name}")
    assert offenders == []
