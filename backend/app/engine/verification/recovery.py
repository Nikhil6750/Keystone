"""Recovery Policy: "what should happen next?" -- a deterministic decision
made *after* verification, never an execution.

**Architecture separation, load-bearing:**

- Stage 3 (`app.engine.workflow.retry_runner.RetryingStepRunner`) retries a
  *transient execution failure* of the *same* step/agent type -- a
  `StepRunnerError` whose `error_type` is classified retryable (timeouts,
  transient network errors). It has no awareness of verification and never
  reroutes.
- Stage 4E (`decide_recovery` below) reacts to a *verification* outcome
  (`AggregatedVerification.overall_status`) -- the step executed
  successfully at the transport level, but its *output* failed or could not
  be confirmed to satisfy its `ExpectedOutcome`(s). This module never
  imports `RetryingStepRunner`/`RetryPolicy`/`CircuitBreakerRegistry` and
  never sleeps or loops -- `decide_recovery` returns one decision per call;
  any actual re-attempt is a separate, later call by the caller (a future
  Orchestrator, out of scope here), not a loop inside this module.

**Rerouting** (`reroute`) asks the existing Stage 4B `Router` for the next
`RoutingDecision` -- it never executes the selected agent, never changes
`Router`/scorer scoring semantics, and never bypasses a hard constraint: a
previously-failed agent type is excluded via the same
`RoutingConstraints.excluded_agent_types` mechanism the Router already
hard-enforces first (`app.engine.routing.scorer._eligibility_violation_detail`),
not a new bypass path.

**Determinism:** `decide_recovery` is a pure function of its
caller-supplied `attempt_number`, `policy`, and `verification`/history
arguments -- no randomness, no internal mutable counter, no current-time
check. The same inputs always produce the same `RecoveryDecision`.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

from app.contracts.routing import RoutingDecision, RoutingRequest
from app.contracts.verification import VerificationStatus
from app.engine.routing.availability import CandidateAgent
from app.engine.routing.router import Router
from app.engine.verification.aggregation import AggregatedVerification


class RecoveryAction(StrEnum):
    """What Stage 4E decided should happen next, after verification."""

    ACCEPT = "accept"
    RETRY_SAME = "retry_same"
    REROUTE = "reroute"
    REQUEST_CONSENSUS = "request_consensus"
    HUMAN_REVIEW = "human_review"
    FAIL = "fail"


@dataclass(frozen=True)
class RecoveryPolicy:
    """Bounds and permissions for `decide_recovery`. `max_attempts` bounds
    the whole recovery cycle (routing+execution+verification attempts, a
    distinct counter from Stage 3's own `WorkflowStepDefinition.max_attempts`
    transient-retry budget) -- this is what prevents an infinite
    reroute/retry loop, not any state this module tracks internally."""

    max_attempts: int = 3
    allow_retry_same: bool = True
    allow_reroute: bool = True
    allow_consensus: bool = False
    consensus_after_attempts: int = 2

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.consensus_after_attempts < 1:
            raise ValueError("consensus_after_attempts must be at least 1")


@dataclass(frozen=True)
class RecoveryDecision:
    """One deterministic recovery verdict. `reason` is always a plain,
    observable-fact sentence (never a model's reasoning) so a later
    Keystone explanation layer can say why retry/reroute/consensus/failure
    was chosen without re-deriving it."""

    action: RecoveryAction
    reason: str
    attempt_number: int
    verification_status: VerificationStatus
    excluded_agent_types: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("reason must not be blank")
        if self.attempt_number < 1:
            raise ValueError("attempt_number must be at least 1")


_DEFAULT_POLICY = RecoveryPolicy()


def decide_recovery(
    *,
    verification: AggregatedVerification,
    attempt_number: int,
    policy: RecoveryPolicy = _DEFAULT_POLICY,
    previously_excluded_agent_types: Iterable[str] = (),
) -> RecoveryDecision:
    """Decide what should happen next, given one verification outcome.

    Fixed, documented priority for a non-passing verification
    (`FAILED`/`INCONCLUSIVE`): bounded failure first, then consensus (if due
    and allowed), then reroute (if allowed), then retry-same (if allowed),
    else terminal failure. `PASSED` always accepts; `REQUIRES_HUMAN_REVIEW`
    always routes to a human, regardless of attempt count -- an explicit
    human-review requirement is never something more attempts resolve.
    """
    if attempt_number < 1:
        raise ValueError("attempt_number must be at least 1")

    status = verification.overall_status
    excluded = tuple(sorted(set(previously_excluded_agent_types)))

    if status is VerificationStatus.PASSED:
        return RecoveryDecision(
            action=RecoveryAction.ACCEPT,
            reason="all required verification checks passed",
            attempt_number=attempt_number,
            verification_status=status,
            excluded_agent_types=excluded,
        )

    if status is VerificationStatus.REQUIRES_HUMAN_REVIEW:
        return RecoveryDecision(
            action=RecoveryAction.HUMAN_REVIEW,
            reason="verification requires explicit human review",
            attempt_number=attempt_number,
            verification_status=status,
            excluded_agent_types=excluded,
        )

    # status is FAILED or INCONCLUSIVE.
    if attempt_number >= policy.max_attempts:
        return RecoveryDecision(
            action=RecoveryAction.FAIL,
            reason=f"reached max_attempts={policy.max_attempts} without a passing verification",
            attempt_number=attempt_number,
            verification_status=status,
            excluded_agent_types=excluded,
        )

    if policy.allow_consensus and attempt_number >= policy.consensus_after_attempts:
        return RecoveryDecision(
            action=RecoveryAction.REQUEST_CONSENSUS,
            reason=(
                f"verification {status.value} after {attempt_number} attempt(s); "
                "requesting independent consensus"
            ),
            attempt_number=attempt_number,
            verification_status=status,
            excluded_agent_types=excluded,
        )

    if policy.allow_reroute:
        return RecoveryDecision(
            action=RecoveryAction.REROUTE,
            reason=f"verification {status.value}; rerouting to a different candidate",
            attempt_number=attempt_number,
            verification_status=status,
            excluded_agent_types=excluded,
        )

    if policy.allow_retry_same:
        return RecoveryDecision(
            action=RecoveryAction.RETRY_SAME,
            reason=f"verification {status.value}; retrying the same candidate",
            attempt_number=attempt_number,
            verification_status=status,
            excluded_agent_types=excluded,
        )

    return RecoveryDecision(
        action=RecoveryAction.FAIL,
        reason="no recovery action is permitted by policy",
        attempt_number=attempt_number,
        verification_status=status,
        excluded_agent_types=excluded,
    )


def build_reroute_request(
    original_request: RoutingRequest, *, additionally_excluded_agent_types: Iterable[str]
) -> RoutingRequest:
    """A new `RoutingRequest` preserving every field of `original_request`
    (`task_type`, `required_capabilities`, `repository`, ... -- whatever an
    earlier "compiler" stage already derived from the originating
    `TaskSpec`) except `constraints.excluded_agent_types`, which gains the
    newly-excluded agent type(s), and `manual_override_agent_type`, which is
    always cleared: re-forcing the same manual pick that already failed
    verification would defeat the purpose of rerouting, and (since it is
    now in `excluded_agent_types`) would make `Router` raise
    `UnsafeManualOverrideError` rather than reroute at all."""
    new_excluded = sorted(
        set(original_request.constraints.excluded_agent_types)
        | set(additionally_excluded_agent_types)
    )
    new_constraints = original_request.constraints.model_copy(
        update={"excluded_agent_types": new_excluded}
    )
    return original_request.model_copy(
        update={"constraints": new_constraints, "manual_override_agent_type": None}
    )


def reroute(
    router: Router,
    original_request: RoutingRequest,
    candidates: list[CandidateAgent],
    *,
    additionally_excluded_agent_types: Iterable[str],
) -> RoutingDecision:
    """Ask the existing Stage 4B `Router` for the next candidate, excluding
    every agent type recovery policy has ruled out. Calls `Router.route`
    completely unmodified -- no scoring semantics are touched here -- and
    never executes the selected agent; the caller decides what to do with
    the returned `RoutingDecision`."""
    new_request = build_reroute_request(
        original_request, additionally_excluded_agent_types=additionally_excluded_agent_types
    )
    return router.route(new_request, candidates)


__all__ = [
    "RecoveryAction",
    "RecoveryDecision",
    "RecoveryPolicy",
    "build_reroute_request",
    "decide_recovery",
    "reroute",
]
