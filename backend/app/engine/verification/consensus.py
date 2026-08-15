"""Verification-based consensus -- never hidden-reasoning voting.

Each candidate's output is verified **independently** first (by the caller,
via `verifier.verify_many`, before it ever reaches this module); consensus
here only combines already-computed `AggregatedVerification`s and the
candidates' own observable output values. Nothing here ever compares a
model's internal reasoning, prompt, or scratchpad -- only
`VerificationStatus` and one plain, caller-named observable field
(`comparison_key`, default `"output"`) of each candidate's `ObservedOutcome`.

**Rules:**

- Two or more independently `PASSED` candidates reach `AGREEMENT` only when
  *every* `PASSED` candidate's `comparison_key` value is present and exactly
  equal. A single candidate missing that value, or any value that differs,
  is never assumed equal -- it always falls through to `CONFLICT`, never a
  silent majority pick. This is deliberately strict: with three candidates
  where two happen to match and one differs, the result is still `CONFLICT`
  (not "2 out of 3 win"), because agreement must be confirmed for the whole
  passing set, never inferred by counting.
- Exactly one `PASSED` candidate, with the rest `FAILED`/`INCONCLUSIVE`/
  `REQUIRES_HUMAN_REVIEW`, is `SINGLE_PASS` -- clearly identified, no
  ambiguity to resolve.
- Every candidate `FAILED` is `ALL_FAILED`.
- No candidate `PASSED`, but not every candidate strictly `FAILED` either
  (some `INCONCLUSIVE`/`REQUIRES_HUMAN_REVIEW` mixed in) is
  `INSUFFICIENT_EVIDENCE` -- distinct from `ALL_FAILED`, since "every
  candidate objectively failed" is a stronger, more actionable signal than
  "we simply couldn't confirm any of them."
- An empty candidate list is also `INSUFFICIENT_EVIDENCE`.
- A candidate pool containing more than one entry for the same `agent_type`
  is ambiguous and rejected outright (`VerificationEngineError`) -- never
  silently deduplicated or scored as if the repeated entries were
  independent evidence (`codex, codex, claude` must never be counted as 3
  independent candidates).
"""

import json
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.contracts.verification import VerificationStatus
from app.engine.verification.aggregation import AggregatedVerification
from app.engine.verification.errors import VerificationEngineError
from app.engine.verification.evaluators import ObservedOutcome
from app.engine.verification.recovery import RecoveryAction


class ConsensusOutcome(StrEnum):
    """The shape of agreement (or disagreement) found across independently
    verified candidate outputs."""

    AGREEMENT = "agreement"
    SINGLE_PASS = "single_pass"
    CONFLICT = "conflict"
    ALL_FAILED = "all_failed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True)
class ConsensusCandidate:
    """One candidate's independent, already-computed verification outcome."""

    agent_type: str
    verification: AggregatedVerification
    observed: ObservedOutcome

    def __post_init__(self) -> None:
        if not self.agent_type.strip():
            raise ValueError("agent_type must not be blank")


@dataclass(frozen=True)
class ConsensusResult:
    """The deterministic outcome of comparing independently verified candidates."""

    outcome: ConsensusOutcome
    recommended_action: RecoveryAction
    passed_agent_types: tuple[str, ...] = field(default_factory=tuple)
    failed_agent_types: tuple[str, ...] = field(default_factory=tuple)
    agreed_agent_types: tuple[str, ...] = field(default_factory=tuple)
    accepted_agent_type: str | None = None
    summary: str = ""


def _comparison_signature(value: Any) -> str:
    """A deterministic, order-independent string signature for grouping
    candidate outputs by equality. JSON-serializable values (the expected
    case for observable evidence) are canonicalized via sorted-key JSON;
    anything else falls back to `repr` -- still deterministic for any
    single run, just not guaranteed order-independent for exotic types."""
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except TypeError:
        return repr(value)


def evaluate_consensus(
    candidates: list[ConsensusCandidate], *, comparison_key: str = "output"
) -> ConsensusResult:
    """Combine independently verified `candidates` into one `ConsensusResult`.
    See module docstring for the exact rule table. Deterministic: identical
    `candidates` (in any order, since results are agent-type-sorted) always
    produce an identical `ConsensusResult`.

    Raises `VerificationEngineError` if `candidates` contains more than one
    entry for the same `agent_type` -- an ambiguous pool, never silently
    resolved by counting duplicates as independent agreement."""
    agent_type_counts = Counter(c.agent_type for c in candidates)
    duplicate_types = sorted(
        agent_type for agent_type, count in agent_type_counts.items() if count > 1
    )
    if duplicate_types:
        raise VerificationEngineError(
            "duplicate candidate agent_type(s) in consensus pool: " + ", ".join(duplicate_types)
        )

    if not candidates:
        return ConsensusResult(
            outcome=ConsensusOutcome.INSUFFICIENT_EVIDENCE,
            recommended_action=RecoveryAction.HUMAN_REVIEW,
            summary="no candidate outputs were provided for consensus",
        )

    passed = sorted(
        (c for c in candidates if c.verification.overall_status is VerificationStatus.PASSED),
        key=lambda c: c.agent_type,
    )
    failed_types = tuple(
        sorted(
            c.agent_type
            for c in candidates
            if c.verification.overall_status is VerificationStatus.FAILED
        )
    )
    passed_types = tuple(c.agent_type for c in passed)

    if not passed:
        if failed_types and len(failed_types) == len(candidates):
            return ConsensusResult(
                outcome=ConsensusOutcome.ALL_FAILED,
                recommended_action=RecoveryAction.FAIL,
                failed_agent_types=failed_types,
                summary=f"all {len(candidates)} candidate(s) failed verification",
            )
        return ConsensusResult(
            outcome=ConsensusOutcome.INSUFFICIENT_EVIDENCE,
            recommended_action=RecoveryAction.HUMAN_REVIEW,
            failed_agent_types=failed_types,
            summary=(
                "no candidate reached a passing verification and evidence is "
                "insufficient to decide automatically"
            ),
        )

    if len(passed) == 1:
        winner = passed[0]
        return ConsensusResult(
            outcome=ConsensusOutcome.SINGLE_PASS,
            recommended_action=RecoveryAction.ACCEPT,
            passed_agent_types=passed_types,
            failed_agent_types=failed_types,
            accepted_agent_type=winner.agent_type,
            summary=f"'{winner.agent_type}' was the only candidate to pass verification",
        )

    # Two or more candidates passed independently -- compare their
    # observable outputs. Never assume equality: a candidate missing the
    # comparison value is tracked separately and always forces CONFLICT.
    signatures: set[str] = set()
    missing_comparison = False
    for candidate in passed:
        if comparison_key not in candidate.observed.data:
            missing_comparison = True
            continue
        signatures.add(_comparison_signature(candidate.observed.data[comparison_key]))

    if missing_comparison or len(signatures) != 1:
        return ConsensusResult(
            outcome=ConsensusOutcome.CONFLICT,
            recommended_action=RecoveryAction.HUMAN_REVIEW,
            passed_agent_types=passed_types,
            failed_agent_types=failed_types,
            summary=(
                f"{len(passed)} candidates passed verification but their observed outputs "
                "conflict or could not be confirmed identical"
            ),
        )

    agreed_types = passed_types
    representative = agreed_types[0]
    return ConsensusResult(
        outcome=ConsensusOutcome.AGREEMENT,
        recommended_action=RecoveryAction.ACCEPT,
        passed_agent_types=passed_types,
        failed_agent_types=failed_types,
        agreed_agent_types=agreed_types,
        accepted_agent_type=representative,
        summary=(
            f"{len(agreed_types)} candidate(s) independently passed verification with "
            "identical observed output"
        ),
    )


__all__ = ["ConsensusCandidate", "ConsensusOutcome", "ConsensusResult", "evaluate_consensus"]
