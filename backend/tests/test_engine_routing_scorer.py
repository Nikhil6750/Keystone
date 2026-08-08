"""Tests for `eligibility_violation`, `score_candidate`, and
`manual_override_safety_violation`: hard constraint filtering, deterministic
evidence-based scoring, and manual-override safety checks."""

from typing import Any

import pytest

from app.contracts.adapter import AgentDescriptor, RepositoryMetadata
from app.contracts.enums import AgentCapability, AgentStatus, RuntimeKind
from app.contracts.passports import AgentPassportMetricBucket
from app.contracts.routing import RoutingConstraints, RoutingRequest
from app.engine.routing.availability import CandidateAgent
from app.engine.routing.evidence import NullEvidenceProvider
from app.engine.routing.scorer import (
    RoutingWeights,
    eligibility_violation,
    manual_override_safety_violation,
    score_candidate,
)
from app.resilience.circuit_breaker import CircuitState
from tests.support.routing_fakes import FakeEvidenceProvider


def _candidate(
    agent_type: str = "claude_code",
    *,
    capabilities: list[AgentCapability] | None = None,
    status: AgentStatus = AgentStatus.AVAILABLE,
    circuit_state: CircuitState = CircuitState.CLOSED,
    runtime_kind: RuntimeKind = RuntimeKind.AGENT_CLI,
) -> CandidateAgent:
    return CandidateAgent(
        descriptor=AgentDescriptor(
            agent_type=agent_type,
            display_name=agent_type,
            runtime_kind=runtime_kind,
            capabilities=capabilities or [AgentCapability.CODE_GENERATION],
        ),
        status=status,
        circuit_state=circuit_state,
    )


def _request(**overrides: Any) -> RoutingRequest:
    base: dict[str, Any] = {"task_type": "code_generation"}
    base.update(overrides)
    return RoutingRequest.model_validate(base)


# --- Hard eligibility filtering ---------------------------------------------


def test_missing_required_capability_is_ineligible() -> None:
    candidate = _candidate(capabilities=[AgentCapability.DOCUMENTATION])
    request = _request(required_capabilities=[AgentCapability.CODE_GENERATION])
    reason = eligibility_violation(candidate, request, NullEvidenceProvider())
    assert reason == "missing required capabilities: code_generation"


def test_matching_capability_is_eligible() -> None:
    candidate = _candidate(capabilities=[AgentCapability.CODE_GENERATION])
    request = _request(required_capabilities=[AgentCapability.CODE_GENERATION])
    assert eligibility_violation(candidate, request, NullEvidenceProvider()) is None


def test_unavailable_agent_is_excluded() -> None:
    candidate = _candidate(status=AgentStatus.UNAVAILABLE)
    reason = eligibility_violation(candidate, _request(), NullEvidenceProvider())
    assert reason == "agent unavailable"


def test_unknown_status_agent_is_excluded() -> None:
    candidate = _candidate(status=AgentStatus.UNKNOWN)
    reason = eligibility_violation(candidate, _request(), NullEvidenceProvider())
    assert reason == "agent unavailable"


def test_degraded_agent_remains_eligible() -> None:
    candidate = _candidate(status=AgentStatus.DEGRADED)
    assert eligibility_violation(candidate, _request(), NullEvidenceProvider()) is None


def test_open_circuit_excludes_the_candidate() -> None:
    candidate = _candidate(circuit_state=CircuitState.OPEN)
    reason = eligibility_violation(candidate, _request(), NullEvidenceProvider())
    assert reason == "circuit breaker open"


def test_half_open_circuit_remains_eligible() -> None:
    candidate = _candidate(circuit_state=CircuitState.HALF_OPEN)
    assert eligibility_violation(candidate, _request(), NullEvidenceProvider()) is None


def test_excluded_by_routing_constraints() -> None:
    candidate = _candidate(agent_type="codex")
    request = _request(constraints=RoutingConstraints(excluded_agent_types=["codex"]))
    reason = eligibility_violation(candidate, request, NullEvidenceProvider())
    assert reason == "excluded by routing constraints"


def test_minimum_reliability_with_no_evidence_cannot_prove_compliance() -> None:
    candidate = _candidate()
    request = _request(constraints=RoutingConstraints(minimum_reliability=0.5))
    reason = eligibility_violation(candidate, request, NullEvidenceProvider())
    assert reason == "no reliability evidence available to satisfy minimum_reliability"


def test_minimum_reliability_below_threshold_is_excluded() -> None:
    candidate = _candidate()
    evidence = FakeEvidenceProvider(
        overall={"claude_code": AgentPassportMetricBucket(execution_count=10, success_count=3)}
    )
    request = _request(constraints=RoutingConstraints(minimum_reliability=0.5))
    reason = eligibility_violation(candidate, request, evidence)
    assert reason == "reliability below minimum_reliability"


def test_minimum_reliability_at_or_above_threshold_is_eligible() -> None:
    candidate = _candidate()
    evidence = FakeEvidenceProvider(
        overall={"claude_code": AgentPassportMetricBucket(execution_count=10, success_count=8)}
    )
    request = _request(constraints=RoutingConstraints(minimum_reliability=0.5))
    assert eligibility_violation(candidate, request, evidence) is None


def test_max_latency_with_no_evidence_cannot_prove_compliance() -> None:
    candidate = _candidate()
    request = _request(constraints=RoutingConstraints(max_latency_ms=1000.0))
    reason = eligibility_violation(candidate, request, NullEvidenceProvider())
    assert reason == "no latency evidence available to satisfy max_latency_ms"


def test_max_latency_exceeded_is_excluded() -> None:
    candidate = _candidate()
    evidence = FakeEvidenceProvider(
        overall={
            "claude_code": AgentPassportMetricBucket(
                execution_count=10, success_count=10, median_latency_ms=5000.0
            )
        }
    )
    request = _request(constraints=RoutingConstraints(max_latency_ms=1000.0))
    reason = eligibility_violation(candidate, request, evidence)
    assert reason == "latency exceeds max_latency_ms"


def test_max_latency_within_bound_is_eligible() -> None:
    candidate = _candidate()
    evidence = FakeEvidenceProvider(
        overall={
            "claude_code": AgentPassportMetricBucket(
                execution_count=10, success_count=10, median_latency_ms=500.0
            )
        }
    )
    request = _request(constraints=RoutingConstraints(max_latency_ms=1000.0))
    assert eligibility_violation(candidate, request, evidence) is None


def test_max_cost_with_no_evidence_cannot_prove_compliance() -> None:
    """No `RoutingEvidenceProvider` implementation reports real cost data yet
    (see `evidence.py`) — a `max_cost_usd` constraint therefore always
    excludes today, exactly like any other unmet hard constraint."""
    candidate = _candidate()
    request = _request(constraints=RoutingConstraints(max_cost_usd=1.0))
    reason = eligibility_violation(candidate, request, NullEvidenceProvider())
    assert reason == "no cost evidence available to satisfy max_cost_usd"


def test_max_cost_exceeded_is_excluded() -> None:
    candidate = _candidate()
    evidence = FakeEvidenceProvider(cost_usd={"claude_code": 5.0})
    request = _request(constraints=RoutingConstraints(max_cost_usd=1.0))
    reason = eligibility_violation(candidate, request, evidence)
    assert reason == "cost exceeds max_cost_usd"


def test_max_cost_within_bound_is_eligible() -> None:
    candidate = _candidate()
    evidence = FakeEvidenceProvider(cost_usd={"claude_code": 0.5})
    request = _request(constraints=RoutingConstraints(max_cost_usd=1.0))
    assert eligibility_violation(candidate, request, evidence) is None


# --- Scoring -----------------------------------------------------------------


def test_scoring_is_deterministic_for_identical_inputs() -> None:
    evidence = FakeEvidenceProvider(
        overall={"claude_code": AgentPassportMetricBucket(execution_count=10, success_count=7)}
    )
    candidate = _candidate()
    request = _request()
    weights = RoutingWeights()
    first = score_candidate(candidate, request, evidence, weights)
    second = score_candidate(candidate, request, evidence, weights)
    assert first == second


def test_missing_evidence_scores_neutral_not_perfect() -> None:
    candidate = _candidate()
    score = score_candidate(candidate, _request(), NullEvidenceProvider(), RoutingWeights())
    assert score.reliability_score == 0.5
    assert score.task_type_score == 0.5
    assert score.repository_score == 0.5
    assert score.latency_score == 0.5
    assert score.cost_score == 0.5
    assert score.sample_size == 0
    assert score.low_sample_size is True
    assert score.eligible is True  # still a viable bootstrap candidate
    assert score.composite_score == pytest.approx(0.625)
    assert score.composite_score is not None
    assert score.composite_score < 1.0


def test_a_single_lucky_success_does_not_outrank_a_proven_track_record() -> None:
    evidence = FakeEvidenceProvider(
        overall={
            "agent_a": AgentPassportMetricBucket(execution_count=1, success_count=1),
            "agent_b": AgentPassportMetricBucket(execution_count=100, success_count=95),
        }
    )
    score_a = score_candidate(_candidate("agent_a"), _request(), evidence, RoutingWeights())
    score_b = score_candidate(_candidate("agent_b"), _request(), evidence, RoutingWeights())
    assert score_a.reliability_score is not None
    assert score_b.reliability_score is not None
    assert score_a.composite_score is not None
    assert score_b.composite_score is not None
    assert score_a.reliability_score < score_b.reliability_score
    assert score_a.composite_score < score_b.composite_score
    # Documented smoothing formula: (successes + 1) / (executions + 2).
    assert score_a.reliability_score == pytest.approx(2 / 3)
    assert score_b.reliability_score == pytest.approx(96 / 102)


def test_small_sample_is_flagged_low_confidence() -> None:
    evidence = FakeEvidenceProvider(
        overall={"claude_code": AgentPassportMetricBucket(execution_count=2, success_count=2)}
    )
    score = score_candidate(_candidate(), _request(), evidence, RoutingWeights())
    assert score.sample_size == 2
    assert score.low_sample_size is True


def test_sufficiently_large_sample_is_not_flagged() -> None:
    evidence = FakeEvidenceProvider(
        overall={"claude_code": AgentPassportMetricBucket(execution_count=10, success_count=8)}
    )
    score = score_candidate(_candidate(), _request(), evidence, RoutingWeights())
    assert score.sample_size == 10
    assert score.low_sample_size is False


def test_task_specific_evidence_is_used() -> None:
    evidence = FakeEvidenceProvider(
        by_task_type={
            ("claude_code", "debugging"): AgentPassportMetricBucket(
                execution_count=10, success_count=9
            )
        }
    )
    request = _request(task_type="debugging")
    score = score_candidate(_candidate(), request, evidence, RoutingWeights())
    assert score.task_type_score == pytest.approx(10 / 12)


def test_repository_specific_evidence_is_used() -> None:
    evidence = FakeEvidenceProvider(
        by_repository={
            ("claude_code", "repo-1"): AgentPassportMetricBucket(
                execution_count=10, success_count=5
            )
        }
    )
    request = _request(repository=RepositoryMetadata(repository_id="repo-1"))
    score = score_candidate(_candidate(), request, evidence, RoutingWeights())
    assert score.repository_score == pytest.approx(6 / 12)


def test_no_repository_in_request_means_neutral_repository_score() -> None:
    evidence = FakeEvidenceProvider(
        by_repository={
            ("claude_code", "repo-1"): AgentPassportMetricBucket(
                execution_count=10, success_count=5
            )
        }
    )
    score = score_candidate(_candidate(), _request(), evidence, RoutingWeights())
    assert score.repository_score == 0.5


def test_preference_bonus_raises_composite_score_among_otherwise_identical_candidates() -> None:
    request = _request(constraints=RoutingConstraints(preferred_agent_types=["b"]))
    score_a = score_candidate(_candidate("a"), request, NullEvidenceProvider(), RoutingWeights())
    score_b = score_candidate(_candidate("b"), request, NullEvidenceProvider(), RoutingWeights())
    assert score_b.composite_score is not None
    assert score_a.composite_score is not None
    assert score_b.composite_score > score_a.composite_score


def test_no_preference_expressed_scores_everyone_neutrally() -> None:
    score = score_candidate(_candidate("a"), _request(), NullEvidenceProvider(), RoutingWeights())
    assert score.evidence["factor_scores"]["preference"] == 0.5


def test_runtime_kind_carries_no_arbitrary_scoring_bias() -> None:
    """Two otherwise-identical candidates differing only in `runtime_kind`
    must score identically — `runtime_kind` is classificatory, not a quality
    signal (see `docs/contracts.md` and `scorer.py`'s module docstring)."""
    cli = _candidate("cli_agent", runtime_kind=RuntimeKind.AGENT_CLI)
    api = _candidate("api_agent", runtime_kind=RuntimeKind.MODEL_API)
    local = _candidate("local_agent", runtime_kind=RuntimeKind.LOCAL_MODEL)
    hybrid = _candidate("hybrid_agent", runtime_kind=RuntimeKind.HYBRID)
    scores = [
        score_candidate(c, _request(), NullEvidenceProvider(), RoutingWeights())
        for c in (cli, api, local, hybrid)
    ]
    composites = {score.composite_score for score in scores}
    assert len(composites) == 1


def test_composite_score_never_exceeds_one_or_drops_below_zero() -> None:
    evidence = FakeEvidenceProvider(
        overall={"claude_code": AgentPassportMetricBucket(execution_count=1000, success_count=1000)}
    )
    request = _request(constraints=RoutingConstraints(preferred_agent_types=["claude_code"]))
    score = score_candidate(_candidate(), request, evidence, RoutingWeights())
    assert score.composite_score is not None
    assert 0.0 <= score.composite_score <= 1.0


def test_score_evidence_dict_exposes_factor_level_breakdown() -> None:
    """Deterministic factor-level values must be preserved (not collapsed to
    only the composite) so Stage 4C's Explainability Engine can later build
    `ScoreContribution`/`EvidenceItem` data without recomputation."""
    score = score_candidate(_candidate(), _request(), NullEvidenceProvider(), RoutingWeights())
    factor_scores = score.evidence["factor_scores"]
    factor_weights = score.evidence["factor_weights"]
    expected_factors = {
        "capability",
        "overall_reliability",
        "task_reliability",
        "repository_reliability",
        "latency",
        "cost",
        "availability",
        "preference",
    }
    assert set(factor_scores) == expected_factors
    assert set(factor_weights) == expected_factors
    assert all(0.0 <= value <= 1.0 for value in factor_scores.values())
    assert sum(factor_weights.values()) == pytest.approx(1.0)


# --- RoutingWeights validation ------------------------------------------------


def test_routing_weights_reject_negative_weight() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        RoutingWeights(capability_weight=-0.1)


def test_routing_weights_reject_non_unit_sum() -> None:
    with pytest.raises(ValueError, match="must sum to 1.0"):
        RoutingWeights(capability_weight=0.5)


def test_routing_weights_reject_non_positive_target_latency() -> None:
    with pytest.raises(ValueError, match="target_latency_ms must be positive"):
        RoutingWeights(target_latency_ms=0.0)


def test_default_routing_weights_sum_to_one() -> None:
    weights = RoutingWeights()
    total = (
        weights.capability_weight
        + weights.overall_reliability_weight
        + weights.task_reliability_weight
        + weights.repository_reliability_weight
        + weights.latency_weight
        + weights.cost_weight
        + weights.availability_weight
        + weights.preference_weight
    )
    assert total == pytest.approx(1.0)


# --- Manual override safety ---------------------------------------------------


def test_manual_override_safety_violation_none_for_healthy_candidate() -> None:
    candidate = _candidate()
    assert manual_override_safety_violation(candidate, _request()) is None


def test_manual_override_safety_violation_for_unavailable_candidate() -> None:
    candidate = _candidate(status=AgentStatus.UNAVAILABLE)
    assert manual_override_safety_violation(candidate, _request()) == "agent unavailable"


def test_manual_override_safety_violation_for_open_circuit() -> None:
    candidate = _candidate(circuit_state=CircuitState.OPEN)
    assert manual_override_safety_violation(candidate, _request()) == "circuit breaker open"


def test_manual_override_safety_violation_for_missing_capability() -> None:
    candidate = _candidate(capabilities=[AgentCapability.DOCUMENTATION])
    request = _request(required_capabilities=[AgentCapability.CODE_GENERATION])
    violation = manual_override_safety_violation(candidate, request)
    assert violation == "missing required capabilities: code_generation"


def test_manual_override_safety_violation_ignores_soft_policy_constraints() -> None:
    """A manual override is a privileged bypass of routing *policy*
    (exclusion lists, reliability/cost/latency thresholds, preference) —
    only hard operational safety is still enforced."""
    candidate = _candidate(agent_type="codex")
    request = _request(
        constraints=RoutingConstraints(
            excluded_agent_types=["codex"], minimum_reliability=0.99, max_cost_usd=0.0
        )
    )
    assert manual_override_safety_violation(candidate, request) is None
