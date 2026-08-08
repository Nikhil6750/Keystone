"""Tests for `app.engine.verification.consensus`: verification-based
consensus using only observable outputs and verification status, never
hidden reasoning or majority-vote-by-count heuristics."""

from datetime import UTC, datetime

import pytest

from app.contracts.verification import VerificationStatus
from app.engine.verification.aggregation import AggregatedVerification
from app.engine.verification.consensus import (
    ConsensusCandidate,
    ConsensusOutcome,
    evaluate_consensus,
)
from app.engine.verification.errors import VerificationEngineError
from app.engine.verification.evaluators import ObservedOutcome
from app.engine.verification.recovery import RecoveryAction

_NOW = datetime.now(UTC)


def _candidate(
    agent_type: str, status: VerificationStatus, output: object | None = None
) -> ConsensusCandidate:
    data = {} if output is None else {"output": output}
    return ConsensusCandidate(
        agent_type=agent_type,
        verification=AggregatedVerification(
            overall_status=status, checks=[], summary="x", created_at=_NOW
        ),
        observed=ObservedOutcome(data),
    )


def test_identical_verified_outputs_reach_agreement() -> None:
    candidates = [
        _candidate("claude_code", VerificationStatus.PASSED, "same result"),
        _candidate("codex", VerificationStatus.PASSED, "same result"),
    ]
    result = evaluate_consensus(candidates)
    assert result.outcome is ConsensusOutcome.AGREEMENT
    assert result.recommended_action is RecoveryAction.ACCEPT
    assert set(result.agreed_agent_types) == {"claude_code", "codex"}


def test_one_pass_others_fail_is_single_pass() -> None:
    candidates = [
        _candidate("claude_code", VerificationStatus.PASSED, "result"),
        _candidate("codex", VerificationStatus.FAILED),
        _candidate("gemini", VerificationStatus.FAILED),
    ]
    result = evaluate_consensus(candidates)
    assert result.outcome is ConsensusOutcome.SINGLE_PASS
    assert result.accepted_agent_type == "claude_code"
    assert result.recommended_action is RecoveryAction.ACCEPT


def test_conflicting_passing_outputs_are_never_silently_agreement() -> None:
    candidates = [
        _candidate("claude_code", VerificationStatus.PASSED, "result A"),
        _candidate("codex", VerificationStatus.PASSED, "result B"),
    ]
    result = evaluate_consensus(candidates)
    assert result.outcome is ConsensusOutcome.CONFLICT
    assert result.recommended_action is RecoveryAction.HUMAN_REVIEW
    assert result.agreed_agent_types == ()


def test_majority_match_does_not_override_a_conflicting_minority() -> None:
    """Two candidates agreeing and one disagreeing must still be CONFLICT --
    never a silent 2-out-of-3 majority pick."""
    candidates = [
        _candidate("a", VerificationStatus.PASSED, "same"),
        _candidate("b", VerificationStatus.PASSED, "same"),
        _candidate("c", VerificationStatus.PASSED, "different"),
    ]
    result = evaluate_consensus(candidates)
    assert result.outcome is ConsensusOutcome.CONFLICT


def test_all_fail_is_all_failed() -> None:
    candidates = [
        _candidate("claude_code", VerificationStatus.FAILED),
        _candidate("codex", VerificationStatus.FAILED),
    ]
    result = evaluate_consensus(candidates)
    assert result.outcome is ConsensusOutcome.ALL_FAILED
    assert result.recommended_action is RecoveryAction.FAIL


def test_insufficient_evidence_when_no_pass_and_not_all_fail() -> None:
    candidates = [
        _candidate("claude_code", VerificationStatus.INCONCLUSIVE),
        _candidate("codex", VerificationStatus.REQUIRES_HUMAN_REVIEW),
    ]
    result = evaluate_consensus(candidates)
    assert result.outcome is ConsensusOutcome.INSUFFICIENT_EVIDENCE
    assert result.recommended_action is RecoveryAction.HUMAN_REVIEW


def test_insufficient_evidence_when_no_candidates() -> None:
    result = evaluate_consensus([])
    assert result.outcome is ConsensusOutcome.INSUFFICIENT_EVIDENCE


def test_passed_candidate_missing_comparison_value_is_conflict_not_agreement() -> None:
    """A passing candidate with no observable output to compare must never
    be assumed to agree with another passing candidate."""
    candidates = [
        _candidate("claude_code", VerificationStatus.PASSED, "result"),
        _candidate("codex", VerificationStatus.PASSED, None),
    ]
    result = evaluate_consensus(candidates)
    assert result.outcome is ConsensusOutcome.CONFLICT


def test_consensus_never_depends_on_chain_of_thought_fields() -> None:
    """Only VerificationStatus and the named comparison_key ever factor into
    the outcome -- verified by using a custom comparison_key and confirming
    unrelated data keys have no effect."""
    a = ConsensusCandidate(
        agent_type="claude_code",
        verification=AggregatedVerification(VerificationStatus.PASSED, [], "x", _NOW),
        observed=ObservedOutcome({"answer": 42, "unrelated_field": "irrelevant text"}),
    )
    b = ConsensusCandidate(
        agent_type="codex",
        verification=AggregatedVerification(VerificationStatus.PASSED, [], "x", _NOW),
        observed=ObservedOutcome({"answer": 42, "unrelated_field": "something else entirely"}),
    )
    result = evaluate_consensus([a, b], comparison_key="answer")
    assert result.outcome is ConsensusOutcome.AGREEMENT


def test_consensus_result_is_deterministic() -> None:
    candidates = [
        _candidate("claude_code", VerificationStatus.PASSED, "result"),
        _candidate("codex", VerificationStatus.PASSED, "result"),
    ]
    first = evaluate_consensus(candidates)
    for _ in range(20):
        again = evaluate_consensus(candidates)
        assert again.outcome == first.outcome
        assert again.agreed_agent_types == first.agreed_agent_types
        assert again.accepted_agent_type == first.accepted_agent_type


# --- duplicate candidates (P1) -----------------------------------------------------------


def test_duplicate_agent_type_is_rejected_not_counted_as_independent_candidates() -> None:
    """`codex, codex, claude` must never be treated as 3 independent votes --
    a duplicate pool is ambiguous and rejected outright."""
    candidates = [
        _candidate("codex", VerificationStatus.PASSED, "result"),
        _candidate("codex", VerificationStatus.PASSED, "result"),
        _candidate("claude", VerificationStatus.FAILED),
    ]
    with pytest.raises(VerificationEngineError, match="codex"):
        evaluate_consensus(candidates)


def test_duplicate_agent_type_rejected_even_with_conflicting_verdicts() -> None:
    """Duplicates are rejected purely on `agent_type` identity -- even if
    the repeated entries happen to disagree, they are still an ambiguous
    pool, never resolved by picking one."""
    candidates = [
        _candidate("codex", VerificationStatus.PASSED, "result A"),
        _candidate("codex", VerificationStatus.FAILED),
    ]
    with pytest.raises(VerificationEngineError):
        evaluate_consensus(candidates)


def test_no_duplicate_agent_types_does_not_raise() -> None:
    candidates = [
        _candidate("codex", VerificationStatus.PASSED, "result"),
        _candidate("claude", VerificationStatus.FAILED),
    ]
    evaluate_consensus(candidates)  # must not raise
