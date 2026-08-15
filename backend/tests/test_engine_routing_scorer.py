"""Tests for `eligibility_violation`, `score_candidate`: hard constraint
filtering (including numeric robustness), deterministic evidence-based
scoring, and the raw-evidence/reason-code snapshot preserved for Stage 4C."""

import math
from typing import Any

import pytest

from app.contracts.adapter import AgentDescriptor, RepositoryMetadata
from app.contracts.enums import AgentCapability, AgentStatus, RuntimeKind
from app.contracts.passports import AgentPassportMetricBucket
from app.contracts.routing import RoutingConstraints, RoutingRequest
from app.engine.routing.availability import CandidateAgent
from app.engine.routing.evidence import NullEvidenceProvider
from app.engine.routing.scorer import (
    COST_ABOVE_THRESHOLD,
    COST_EVIDENCE_INVALID,
    COST_EVIDENCE_UNAVAILABLE,
    LATENCY_ABOVE_THRESHOLD,
    LATENCY_EVIDENCE_INVALID,
    LATENCY_EVIDENCE_UNAVAILABLE,
    MISSING_CAPABILITY,
    RELIABILITY_BELOW_THRESHOLD,
    RELIABILITY_EVIDENCE_UNAVAILABLE,
    RoutingWeights,
    eligibility_violation,
    score_candidate,
)
from app.engine.routing.scorer import _eligibility_violation_detail as violation_detail
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


def test_minimum_reliability_exact_boundary_is_eligible() -> None:
    candidate = _candidate()
    evidence = FakeEvidenceProvider(
        overall={"claude_code": AgentPassportMetricBucket(execution_count=10, success_count=5)}
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


def test_max_latency_exact_boundary_is_eligible() -> None:
    candidate = _candidate()
    evidence = FakeEvidenceProvider(
        overall={
            "claude_code": AgentPassportMetricBucket(
                execution_count=10, success_count=10, median_latency_ms=1000.0
            )
        }
    )
    request = _request(constraints=RoutingConstraints(max_latency_ms=1000.0))
    assert eligibility_violation(candidate, request, evidence) is None


def test_max_cost_with_no_evidence_cannot_prove_compliance() -> None:
    """No `RoutingEvidenceProvider` implementation reports real cost data yet
    (see `evidence.py`) — a `max_cost_usd` constraint therefore always
    excludes today, exactly like any other unmet hard constraint. This is
    documented, intentional product behavior, not a bug."""
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


def test_max_cost_exact_boundary_is_eligible() -> None:
    candidate = _candidate()
    evidence = FakeEvidenceProvider(cost_usd={"claude_code": 1.0})
    request = _request(constraints=RoutingConstraints(max_cost_usd=1.0))
    assert eligibility_violation(candidate, request, evidence) is None


def test_zero_cost_is_not_confused_with_missing_cost() -> None:
    candidate = _candidate()
    evidence = FakeEvidenceProvider(cost_usd={"claude_code": 0.0})
    request = _request(constraints=RoutingConstraints(max_cost_usd=0.0))
    assert eligibility_violation(candidate, request, evidence) is None


# --- Numeric robustness: hard constraints -----------------------------------


@pytest.mark.parametrize("bad_cost", [float("nan"), float("inf"), float("-inf"), -5.0])
def test_invalid_cost_evidence_cannot_satisfy_a_hard_cost_constraint(bad_cost: float) -> None:
    candidate = _candidate()
    evidence = FakeEvidenceProvider(cost_usd={"claude_code": bad_cost})
    request = _request(constraints=RoutingConstraints(max_cost_usd=1.0))
    reason = eligibility_violation(candidate, request, evidence)
    assert reason == "cost evidence is invalid and cannot satisfy max_cost_usd"


@pytest.mark.parametrize("bad_cost", [float("nan"), float("inf"), float("-inf"), -5.0])
def test_invalid_cost_evidence_scores_neutral_not_perfect(bad_cost: float) -> None:
    candidate = _candidate()
    evidence = FakeEvidenceProvider(cost_usd={"claude_code": bad_cost})
    score = score_candidate(candidate, _request(), evidence, RoutingWeights())
    assert score.cost_score == 0.5


@pytest.mark.parametrize("bad_latency", [float("nan"), float("inf"), float("-inf"), -500.0])
def test_invalid_latency_evidence_cannot_satisfy_a_hard_latency_constraint(
    bad_latency: float,
) -> None:
    """`median_latency_ms` is itself a validated `AgentPassportMetricBucket`
    field (rejects NaN/inf/negative at construction — see
    `test_contracts_passports.py`), so the realistic path to "invalid" here
    is a duck-typed evidence-provider object that skips Pydantic entirely;
    `AgentPassportMetricBucket.model_construct` simulates exactly that,
    bypassing validation the way a non-conforming future implementation
    might."""
    candidate = _candidate()
    bucket = AgentPassportMetricBucket.model_construct(
        execution_count=10, success_count=10, median_latency_ms=bad_latency
    )
    evidence = FakeEvidenceProvider(overall={"claude_code": bucket})
    request = _request(constraints=RoutingConstraints(max_latency_ms=1000.0))
    reason = eligibility_violation(candidate, request, evidence)
    assert reason == "latency evidence is invalid and cannot satisfy max_latency_ms"


@pytest.mark.parametrize("bad_latency", [float("nan"), float("inf"), float("-inf"), -500.0])
def test_invalid_latency_evidence_scores_neutral_not_perfect(bad_latency: float) -> None:
    candidate = _candidate()
    bucket = AgentPassportMetricBucket.model_construct(
        execution_count=10, success_count=10, median_latency_ms=bad_latency
    )
    evidence = FakeEvidenceProvider(overall={"claude_code": bucket})
    score = score_candidate(candidate, _request(), evidence, RoutingWeights())
    assert score.latency_score == 0.5


def test_malformed_bucket_reliability_defensively_stays_bounded() -> None:
    """`AgentPassportMetricBucket` itself now rejects `success_count >
    execution_count` at construction; `model_construct` bypasses that to
    simulate a non-conforming duck-typed evidence object, proving the
    scorer's own defensive clamp (not just the contract) holds the line."""
    candidate = _candidate()
    bucket = AgentPassportMetricBucket.model_construct(execution_count=2, success_count=5)
    evidence = FakeEvidenceProvider(overall={"claude_code": bucket})
    score = score_candidate(candidate, _request(), evidence, RoutingWeights())
    assert score.reliability_score is not None
    assert 0.0 <= score.reliability_score <= 1.0


def test_malformed_bucket_negative_counts_defensively_stays_bounded() -> None:
    candidate = _candidate()
    bucket = AgentPassportMetricBucket.model_construct(execution_count=-5, success_count=-3)
    evidence = FakeEvidenceProvider(overall={"claude_code": bucket})
    score = score_candidate(candidate, _request(), evidence, RoutingWeights())
    assert score.reliability_score is not None
    assert 0.0 <= score.reliability_score <= 1.0


def test_contract_rejects_malformed_bucket_at_construction() -> None:
    """The primary defense: a real (non-`model_construct`) evidence provider
    cannot hand back a bucket with `success_count > execution_count`,
    negative counts, or non-finite/negative latency at all."""
    with pytest.raises(Exception, match="success_count"):
        AgentPassportMetricBucket(execution_count=2, success_count=5)
    for bad in (float("nan"), float("inf"), float("-inf"), -1.0):
        with pytest.raises(Exception, match="latency"):
            AgentPassportMetricBucket(median_latency_ms=bad)
    for field_name in ("execution_count", "success_count", "failure_count"):
        with pytest.raises(Exception, match="negative"):
            AgentPassportMetricBucket.model_validate({field_name: -1})


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


@pytest.mark.parametrize(
    ("successes", "executions", "expected"),
    [
        (0, 0, 0.5),
        (1, 1, 2 / 3),
        (0, 1, 1 / 3),
        (2, 2, 3 / 4),
        (5, 5, 6 / 7),
        (5, 10, 0.5),
        (50, 100, 0.5),
        (95, 100, 96 / 102),
        (950, 1000, 951 / 1002),
    ],
)
def test_smoothing_formula_matches_documented_values(
    successes: int, executions: int, expected: float
) -> None:
    evidence = FakeEvidenceProvider(
        overall={
            "claude_code": AgentPassportMetricBucket(
                execution_count=executions, success_count=successes
            )
        }
    )
    score = score_candidate(_candidate(), _request(), evidence, RoutingWeights())
    assert score.reliability_score == pytest.approx(expected)


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


def test_huge_valid_counts_do_not_overflow_or_misbehave() -> None:
    evidence = FakeEvidenceProvider(
        overall={
            "claude_code": AgentPassportMetricBucket(
                execution_count=1_000_000, success_count=999_999
            )
        }
    )
    score = score_candidate(_candidate(), _request(), evidence, RoutingWeights())
    assert score.reliability_score is not None
    assert math.isfinite(score.reliability_score)
    assert 0.0 <= score.reliability_score <= 1.0
    assert score.sample_size == 1_000_000


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


# --- Effective required capabilities (RoutingRequest + RoutingConstraints) --


def test_request_only_required_capability_is_enforced() -> None:
    candidate = _candidate(capabilities=[AgentCapability.DOCUMENTATION])
    request = _request(required_capabilities=[AgentCapability.CODE_GENERATION])
    assert (
        eligibility_violation(candidate, request, NullEvidenceProvider())
        == "missing required capabilities: code_generation"
    )


def test_constraints_only_required_capability_is_enforced() -> None:
    candidate = _candidate(capabilities=[AgentCapability.DOCUMENTATION])
    request = _request(constraints=RoutingConstraints(required_capabilities=["code_generation"]))
    assert (
        eligibility_violation(candidate, request, NullEvidenceProvider())
        == "missing required capabilities: code_generation"
    )


def test_request_and_constraints_required_capabilities_are_combined() -> None:
    candidate = _candidate(capabilities=[AgentCapability.CODE_GENERATION])
    request = _request(
        required_capabilities=[AgentCapability.CODE_GENERATION],
        constraints=RoutingConstraints(required_capabilities=["debugging"]),
    )
    reason = eligibility_violation(candidate, request, NullEvidenceProvider())
    assert reason == "missing required capabilities: debugging"


def test_duplicate_capability_across_request_and_constraints_appears_once() -> None:
    candidate = _candidate(capabilities=[AgentCapability.DOCUMENTATION])
    request = _request(
        required_capabilities=[AgentCapability.CODE_GENERATION],
        constraints=RoutingConstraints(required_capabilities=["code_generation"]),
    )
    reason = eligibility_violation(candidate, request, NullEvidenceProvider())
    assert reason == "missing required capabilities: code_generation"


def test_candidate_with_all_effective_capabilities_is_eligible() -> None:
    candidate = _candidate(
        capabilities=[AgentCapability.CODE_GENERATION, AgentCapability.DEBUGGING]
    )
    request = _request(
        required_capabilities=[AgentCapability.CODE_GENERATION],
        constraints=RoutingConstraints(required_capabilities=["debugging"]),
    )
    assert eligibility_violation(candidate, request, NullEvidenceProvider()) is None


# --- Exclusion reason codes (Stage 4C-ready) ---------------------------------


def test_exclusion_reason_codes_are_stable_and_match_the_message() -> None:
    cases: list[tuple[CandidateAgent, RoutingRequest, str]] = [
        (
            _candidate(agent_type="codex"),
            _request(constraints=RoutingConstraints(excluded_agent_types=["codex"])),
            "explicitly_excluded",
        ),
        (
            _candidate(capabilities=[AgentCapability.DOCUMENTATION]),
            _request(required_capabilities=[AgentCapability.CODE_GENERATION]),
            MISSING_CAPABILITY,
        ),
        (_candidate(status=AgentStatus.UNAVAILABLE), _request(), "runtime_unavailable"),
        (_candidate(circuit_state=CircuitState.OPEN), _request(), "circuit_open"),
        (
            _candidate(),
            _request(constraints=RoutingConstraints(minimum_reliability=0.5)),
            RELIABILITY_EVIDENCE_UNAVAILABLE,
        ),
        (
            _candidate(),
            _request(constraints=RoutingConstraints(max_latency_ms=1000.0)),
            LATENCY_EVIDENCE_UNAVAILABLE,
        ),
        (
            _candidate(),
            _request(constraints=RoutingConstraints(max_cost_usd=1.0)),
            COST_EVIDENCE_UNAVAILABLE,
        ),
    ]
    for candidate, request, expected_code in cases:
        detail = violation_detail(candidate, request, NullEvidenceProvider())
        assert detail is not None
        assert detail.code == expected_code


def test_reliability_below_threshold_code() -> None:
    evidence = FakeEvidenceProvider(
        overall={"claude_code": AgentPassportMetricBucket(execution_count=10, success_count=1)}
    )
    request = _request(constraints=RoutingConstraints(minimum_reliability=0.9))
    detail = violation_detail(_candidate(), request, evidence)
    assert detail is not None
    assert detail.code == RELIABILITY_BELOW_THRESHOLD


def test_latency_above_threshold_code() -> None:
    evidence = FakeEvidenceProvider(
        overall={
            "claude_code": AgentPassportMetricBucket(
                execution_count=10, success_count=10, median_latency_ms=9000.0
            )
        }
    )
    request = _request(constraints=RoutingConstraints(max_latency_ms=1000.0))
    detail = violation_detail(_candidate(), request, evidence)
    assert detail is not None
    assert detail.code == LATENCY_ABOVE_THRESHOLD


def test_latency_evidence_invalid_code() -> None:
    bucket = AgentPassportMetricBucket.model_construct(
        execution_count=10, success_count=10, median_latency_ms=float("inf")
    )
    evidence = FakeEvidenceProvider(overall={"claude_code": bucket})
    request = _request(constraints=RoutingConstraints(max_latency_ms=1000.0))
    detail = violation_detail(_candidate(), request, evidence)
    assert detail is not None
    assert detail.code == LATENCY_EVIDENCE_INVALID


def test_cost_above_threshold_code() -> None:
    evidence = FakeEvidenceProvider(cost_usd={"claude_code": 100.0})
    request = _request(constraints=RoutingConstraints(max_cost_usd=1.0))
    detail = violation_detail(_candidate(), request, evidence)
    assert detail is not None
    assert detail.code == COST_ABOVE_THRESHOLD


def test_cost_evidence_invalid_code() -> None:
    evidence = FakeEvidenceProvider(cost_usd={"claude_code": float("nan")})
    request = _request(constraints=RoutingConstraints(max_cost_usd=1.0))
    detail = violation_detail(_candidate(), request, evidence)
    assert detail is not None
    assert detail.code == COST_EVIDENCE_INVALID


def test_eligible_candidate_has_no_exclusion_reason_code() -> None:
    assert violation_detail(_candidate(), _request(), NullEvidenceProvider()) is None


# --- Raw evidence snapshot (Stage 4C readiness) ------------------------------


def test_evidence_snapshot_preserves_raw_success_and_execution_counts() -> None:
    evidence = FakeEvidenceProvider(
        overall={"claude_code": AgentPassportMetricBucket(execution_count=10, success_count=9)},
        by_task_type={
            ("claude_code", "code_generation"): AgentPassportMetricBucket(
                execution_count=4, success_count=3
            )
        },
        by_repository={
            ("claude_code", "repo-1"): AgentPassportMetricBucket(execution_count=2, success_count=1)
        },
    )
    request = _request(repository=RepositoryMetadata(repository_id="repo-1"))
    score = score_candidate(_candidate(), request, evidence, RoutingWeights())
    assert score.evidence["overall"]["execution_count"] == 10
    assert score.evidence["overall"]["success_count"] == 9
    assert score.evidence["overall"]["smoothed_reliability"] == score.reliability_score
    assert score.evidence["task_specific"]["execution_count"] == 4
    assert score.evidence["task_specific"]["success_count"] == 3
    assert score.evidence["repository_specific"]["execution_count"] == 2
    assert score.evidence["repository_specific"]["success_count"] == 1


def test_evidence_snapshot_preserves_raw_latency_and_cost() -> None:
    evidence = FakeEvidenceProvider(
        overall={
            "claude_code": AgentPassportMetricBucket(
                execution_count=1, success_count=1, median_latency_ms=850.0
            )
        },
        cost_usd={"claude_code": 0.03},
    )
    score = score_candidate(_candidate(), _request(), evidence, RoutingWeights())
    assert score.evidence["latency"]["raw_median_latency_ms"] == 850.0
    assert score.evidence["latency"]["score"] == score.latency_score
    assert score.evidence["cost"]["raw_cost_usd"] == 0.03
    assert score.evidence["cost"]["score"] == score.cost_score


def test_evidence_snapshot_preserves_availability_and_preference() -> None:
    candidate = _candidate(status=AgentStatus.DEGRADED, circuit_state=CircuitState.HALF_OPEN)
    request = _request(constraints=RoutingConstraints(preferred_agent_types=["claude_code"]))
    score = score_candidate(candidate, request, NullEvidenceProvider(), RoutingWeights())
    assert score.evidence["availability"]["status"] == "degraded"
    assert score.evidence["availability"]["circuit_state"] == "half_open"
    assert score.evidence["preference"]["preferred"] is True


def test_evidence_snapshot_preserves_capabilities_and_constraints() -> None:
    candidate = _candidate(capabilities=[AgentCapability.CODE_GENERATION])
    request = _request(
        required_capabilities=[AgentCapability.CODE_GENERATION, AgentCapability.DEBUGGING],
        constraints=RoutingConstraints(
            minimum_reliability=0.5, max_latency_ms=1000.0, max_cost_usd=1.0
        ),
    )
    score = score_candidate(candidate, request, NullEvidenceProvider(), RoutingWeights())
    assert score.evidence["capabilities"]["required"] == ["code_generation", "debugging"]
    assert score.evidence["capabilities"]["declared"] == ["code_generation"]
    assert score.evidence["capabilities"]["missing"] == ["debugging"]
    assert score.evidence["constraints"] == {
        "minimum_reliability": 0.5,
        "max_latency_ms": 1000.0,
        "max_cost_usd": 1.0,
    }


def test_evidence_snapshot_includes_exclusion_reason_code_when_ineligible() -> None:
    candidate = _candidate(status=AgentStatus.UNAVAILABLE)
    score = score_candidate(candidate, _request(), NullEvidenceProvider(), RoutingWeights())
    assert score.evidence["exclusion_reason_code"] == "runtime_unavailable"


def test_evidence_snapshot_exclusion_reason_code_is_none_when_eligible() -> None:
    score = score_candidate(_candidate(), _request(), NullEvidenceProvider(), RoutingWeights())
    assert score.evidence["exclusion_reason_code"] is None


def test_evidence_snapshot_flags_bootstrap_when_sample_size_is_zero() -> None:
    score = score_candidate(_candidate(), _request(), NullEvidenceProvider(), RoutingWeights())
    assert score.evidence["bootstrap_no_differentiating_evidence"] is True


def test_evidence_snapshot_does_not_flag_bootstrap_with_real_evidence() -> None:
    evidence = FakeEvidenceProvider(
        overall={"claude_code": AgentPassportMetricBucket(execution_count=10, success_count=8)}
    )
    score = score_candidate(_candidate(), _request(), evidence, RoutingWeights())
    assert score.evidence["bootstrap_no_differentiating_evidence"] is False


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
