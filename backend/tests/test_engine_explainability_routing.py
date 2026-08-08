"""Tests for `app.engine.explainability.routing`: `ScoreContribution`/
`EvidenceItem`/`ExclusionReason` construction from a `RoutingDecision`
snapshot, deterministic decision identity, and malformed-snapshot rejection."""

import math
from datetime import UTC, datetime
from typing import Any

import pytest

from app.contracts.adapter import AgentDescriptor
from app.contracts.enums import AgentCapability, AgentStatus, RuntimeKind
from app.contracts.passports import AgentPassportMetricBucket
from app.contracts.routing import RoutingCandidateScore, RoutingDecision, RoutingRequest
from app.engine.explainability.routing import (
    FACTOR_ORDER,
    ExplainabilityDataError,
    build_evidence_items,
    build_exclusions,
    build_score_contributions,
    compute_decision_id,
    compute_subject_id,
    validate_routing_decision,
)
from app.engine.routing.availability import CandidateAgent
from app.engine.routing.evidence import NullEvidenceProvider
from app.engine.routing.router import Router
from app.engine.routing.scorer import RoutingWeights, score_candidate
from app.resilience.circuit_breaker import CircuitState
from tests.support.routing_fakes import FakeEvidenceProvider

_NOW = datetime.now(UTC)


def _candidate(
    agent_type: str,
    *,
    status: AgentStatus = AgentStatus.AVAILABLE,
    circuit_state: CircuitState = CircuitState.CLOSED,
    capabilities: list[AgentCapability] | None = None,
) -> CandidateAgent:
    return CandidateAgent(
        descriptor=AgentDescriptor(
            agent_type=agent_type,
            display_name=agent_type,
            runtime_kind=RuntimeKind.AGENT_CLI,
            capabilities=capabilities or [AgentCapability.CODE_GENERATION],
        ),
        status=status,
        circuit_state=circuit_state,
    )


def _request(**overrides: Any) -> RoutingRequest:
    base: dict[str, Any] = {"task_type": "code_generation"}
    base.update(overrides)
    return RoutingRequest.model_validate(base)


def _normal_decision() -> RoutingDecision:
    """claude_code (strong evidence) selected over codex (weaker evidence);
    gemini excluded for missing capability; nemotron excluded for an open
    circuit."""
    evidence = FakeEvidenceProvider(
        overall={
            "claude_code": AgentPassportMetricBucket(execution_count=42, success_count=40),
            "codex": AgentPassportMetricBucket(execution_count=42, success_count=30),
        }
    )
    router = Router(evidence=evidence)
    candidates = [
        _candidate("claude_code"),
        _candidate("codex"),
        _candidate("gemini", capabilities=[AgentCapability.CODE_REVIEW]),
        _candidate("nemotron", circuit_state=CircuitState.OPEN),
    ]
    request = _request(required_capabilities=[AgentCapability.CODE_GENERATION])
    return router.route(request, candidates)


def _score(agent_type: str = "claude_code", **request_overrides: Any) -> RoutingCandidateScore:
    request = _request(**request_overrides)
    return score_candidate(
        _candidate(agent_type), request, NullEvidenceProvider(), RoutingWeights()
    )


def _with_evidence(score: RoutingCandidateScore, evidence: dict[str, Any]) -> RoutingCandidateScore:
    return score.model_copy(update={"evidence": evidence})


# --- ScoreContribution -------------------------------------------------------


def test_score_contributions_cover_all_eight_factors_in_deterministic_order() -> None:
    decision = _normal_decision()
    contributions = build_score_contributions(decision)
    for agent_type in ("claude_code", "codex"):
        factor_names = [c.factor_name for c in contributions[agent_type]]
        assert factor_names == list(FACTOR_ORDER)


def test_score_contributions_weighted_contribution_equals_raw_times_weight() -> None:
    decision = _normal_decision()
    contributions = build_score_contributions(decision)
    for contribution in contributions["claude_code"]:
        assert contribution.raw_score is not None
        assert contribution.weighted_contribution == pytest.approx(
            contribution.raw_score * contribution.weight
        )


def test_score_contributions_reliability_sample_sizes_use_bucket_execution_counts() -> None:
    decision = _normal_decision()
    contributions = build_score_contributions(decision)
    by_factor = {c.factor_name: c for c in contributions["claude_code"]}
    assert by_factor["overall_reliability"].sample_size == 42
    assert by_factor["task_reliability"].sample_size == 0
    assert by_factor["repository_reliability"].sample_size == 0


def test_score_contributions_include_excluded_candidates_too() -> None:
    """`score_candidate` always computes the full factor breakdown regardless
    of eligibility -- excluded candidates get a full ScoreContribution list
    too, so "why did the excluded candidate score X" is still answerable."""
    decision = _normal_decision()
    contributions = build_score_contributions(decision)
    assert "gemini" in contributions
    assert "nemotron" in contributions
    assert len(contributions["gemini"]) == len(FACTOR_ORDER)


def test_second_ranked_runtime_has_lower_composite_than_selected() -> None:
    decision = _normal_decision()
    assert decision.selected_agent_type == "claude_code"
    assert decision.fallback_order == ["codex"]
    contributions = build_score_contributions(decision)
    selected_composite = sum(c.weighted_contribution or 0.0 for c in contributions["claude_code"])
    second_composite = sum(c.weighted_contribution or 0.0 for c in contributions["codex"])
    assert selected_composite > second_composite


# --- EvidenceItem --------------------------------------------------------------


def test_evidence_items_for_selected_candidate_cover_all_categories() -> None:
    decision = _normal_decision()
    items = build_evidence_items(decision)
    kinds = {item.kind for item in items}
    assert kinds == {
        "overall_reliability",
        "task_specific_reliability",
        "repository_specific_reliability",
        "latency",
        "cost",
        "availability",
        "preference",
        "capabilities",
        "constraints",
        "bootstrap_no_differentiating_evidence",
    }


def test_evidence_items_overall_reliability_matches_raw_counts() -> None:
    decision = _normal_decision()
    items = build_evidence_items(decision)
    overall = next(item for item in items if item.kind == "overall_reliability")
    assert overall.value == {
        "execution_count": 42,
        "success_count": 40,
        "smoothed_reliability": pytest.approx((40 + 1.0) / (42 + 2.0)),
    }
    assert overall.sample_size == 42


def test_evidence_items_manual_override_has_single_honest_item() -> None:
    router = Router()
    candidates = [_candidate("claude_code")]
    request = _request(manual_override_agent_type="claude_code")
    decision = router.route(request, candidates)
    items = build_evidence_items(decision)
    assert len(items) == 1
    assert items[0].kind == "manual_override"
    assert items[0].value == "claude_code"


def test_evidence_items_no_candidate_selected_is_empty() -> None:
    router = Router()
    request = _request(required_capabilities=[AgentCapability.CODE_REVIEW])
    decision = router.route(request, [_candidate("claude_code")])
    assert decision.selected_agent_type is None
    assert build_evidence_items(decision) == []


# --- ExclusionReason -----------------------------------------------------------


def test_exclusions_built_only_from_ineligible_candidates() -> None:
    decision = _normal_decision()
    exclusions = build_exclusions(decision)
    excluded_ids = {e.candidate_id for e in exclusions}
    assert excluded_ids == {"gemini", "nemotron"}


def test_exclusion_reason_codes_are_machine_readable() -> None:
    decision = _normal_decision()
    exclusions = {e.candidate_id: e for e in build_exclusions(decision)}
    assert exclusions["gemini"].reason_code == "missing_capability"
    assert exclusions["nemotron"].reason_code == "circuit_open"


# --- Decision identity -----------------------------------------------------------


def test_decision_id_is_deterministic_for_identical_decision() -> None:
    decision = _normal_decision()
    replica = RoutingDecision.model_validate(decision.model_dump())
    assert compute_decision_id(decision) == compute_decision_id(replica)


def test_decision_id_changes_when_decision_differs() -> None:
    decision_a = _normal_decision()
    decision_b = _normal_decision()
    mutated = decision_b.model_copy(update={"task_type": "different_task"})
    assert compute_decision_id(decision_a) != compute_decision_id(mutated)


def test_subject_id_uses_selected_agent_type_when_present() -> None:
    decision = _normal_decision()
    assert compute_subject_id(decision) == "claude_code"


def test_subject_id_falls_back_to_task_type_when_nothing_selected() -> None:
    router = Router()
    request = _request(required_capabilities=[AgentCapability.CODE_REVIEW])
    decision = router.route(request, [_candidate("claude_code")])
    assert compute_subject_id(decision) == "code_generation"


# --- Malformed snapshot rejection -----------------------------------------------


def test_validate_rejects_factor_score_key_mismatch() -> None:
    score = _score()
    evidence = dict(score.evidence)
    factor_scores = dict(evidence["factor_scores"])
    del factor_scores["cost"]
    evidence["factor_scores"] = factor_scores
    decision = RoutingDecision(
        task_type="code_generation",
        selected_agent_type="claude_code",
        selected_agent_types=["claude_code"],
        candidates=[_with_evidence(score, evidence)],
        explanation="x",
        decided_at=_NOW,
    )
    with pytest.raises(ExplainabilityDataError):
        validate_routing_decision(decision)


def test_validate_rejects_nan_factor_score() -> None:
    score = _score()
    evidence = dict(score.evidence)
    factor_scores = dict(evidence["factor_scores"])
    factor_scores["cost"] = math.nan
    evidence["factor_scores"] = factor_scores
    decision = RoutingDecision(
        task_type="code_generation",
        selected_agent_type="claude_code",
        selected_agent_types=["claude_code"],
        candidates=[_with_evidence(score, evidence)],
        explanation="x",
        decided_at=_NOW,
    )
    with pytest.raises(ExplainabilityDataError):
        validate_routing_decision(decision)


def test_validate_rejects_infinite_factor_weight() -> None:
    score = _score()
    evidence = dict(score.evidence)
    factor_weights = dict(evidence["factor_weights"])
    factor_weights["cost"] = math.inf
    evidence["factor_weights"] = factor_weights
    decision = RoutingDecision(
        task_type="code_generation",
        selected_agent_type="claude_code",
        selected_agent_types=["claude_code"],
        candidates=[_with_evidence(score, evidence)],
        explanation="x",
        decided_at=_NOW,
    )
    with pytest.raises(ExplainabilityDataError):
        validate_routing_decision(decision)


def test_validate_rejects_out_of_range_factor_score() -> None:
    score = _score()
    evidence = dict(score.evidence)
    factor_scores = dict(evidence["factor_scores"])
    factor_scores["cost"] = 1.5
    evidence["factor_scores"] = factor_scores
    decision = RoutingDecision(
        task_type="code_generation",
        selected_agent_type="claude_code",
        selected_agent_types=["claude_code"],
        candidates=[_with_evidence(score, evidence)],
        explanation="x",
        decided_at=_NOW,
    )
    with pytest.raises(ExplainabilityDataError):
        validate_routing_decision(decision)


def test_validate_rejects_eligible_candidate_with_exclusion_code_set() -> None:
    score = _score()
    assert score.eligible is True
    evidence = dict(score.evidence)
    evidence["exclusion_reason_code"] = "circuit_open"
    decision = RoutingDecision(
        task_type="code_generation",
        selected_agent_type="claude_code",
        selected_agent_types=["claude_code"],
        candidates=[_with_evidence(score, evidence)],
        explanation="x",
        decided_at=_NOW,
    )
    with pytest.raises(ExplainabilityDataError):
        validate_routing_decision(decision)


def test_validate_rejects_excluded_candidate_missing_exclusion_code() -> None:
    excluded = score_candidate(
        _candidate("gemini", capabilities=[AgentCapability.CODE_REVIEW]),
        _request(required_capabilities=[AgentCapability.CODE_GENERATION]),
        NullEvidenceProvider(),
        RoutingWeights(),
    )
    assert excluded.eligible is False
    evidence = dict(excluded.evidence)
    evidence["exclusion_reason_code"] = None
    decision = RoutingDecision(
        task_type="code_generation",
        selected_agent_type=None,
        candidates=[_with_evidence(excluded, evidence)],
        explanation="x",
        decided_at=_NOW,
    )
    with pytest.raises(ExplainabilityDataError):
        validate_routing_decision(decision)


def test_validate_rejects_missing_raw_evidence() -> None:
    score = _score()
    decision = RoutingDecision(
        task_type="code_generation",
        selected_agent_type="claude_code",
        selected_agent_types=["claude_code"],
        candidates=[_with_evidence(score, {})],
        explanation="x",
        decided_at=_NOW,
    )
    with pytest.raises(ExplainabilityDataError):
        validate_routing_decision(decision)


def test_validate_rejects_selected_candidate_not_among_candidates() -> None:
    score = _score(agent_type="codex")
    decision = RoutingDecision(
        task_type="code_generation",
        selected_agent_type="claude_code",
        selected_agent_types=["claude_code"],
        candidates=[score],
        explanation="x",
        decided_at=_NOW,
    )
    with pytest.raises(ExplainabilityDataError):
        validate_routing_decision(decision)


def test_validate_accepts_well_formed_decision() -> None:
    decision = _normal_decision()
    validate_routing_decision(decision)  # must not raise
