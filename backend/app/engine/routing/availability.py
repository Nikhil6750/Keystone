"""What the router needs to know about one candidate agent's current live
state, independent of its historical performance evidence.

Callers assemble `CandidateAgent`s from whatever they already have —
`app.adapters.connection.AgentConnectionCache` for installation/auth/
connection status (collapsed here to the coarser `AgentStatus`, see
`app.contracts.enums`) and `app.resilience.circuit_breaker
.CircuitBreakerRegistry` for circuit state — the router itself has no
dependency on either, so it never duplicates `CircuitBreaker`'s own
open/half-open/closed state machine.
"""

from dataclasses import dataclass

from app.contracts.adapter import AgentDescriptor
from app.contracts.enums import AgentStatus
from app.resilience.circuit_breaker import CircuitState


@dataclass(frozen=True)
class CandidateAgent:
    """One agent the router may consider, with its current live status.

    This is a **point-in-time snapshot**, not a live handle — the caller
    must build it (querying `AgentConnectionCache`/`CircuitBreakerRegistry`
    or equivalent) immediately before calling `Router.route()`. `Router`
    itself has no way to detect or refresh a stale snapshot; it trusts
    `status`/`circuit_state` exactly as given. The gap between "snapshot
    taken" and "execution actually starts" is a real, unavoidable race in
    any snapshot-based design — `Router` deliberately does not pretend
    otherwise, and the execution layer's own circuit breaker/connection
    checks remain the authoritative, real-time gate at call time regardless
    of what the router decided.

    `circuit_state is CircuitState.OPEN` always excludes a candidate.
    `CircuitState.HALF_OPEN` is a deliberate, intentional exception: it
    remains eligible, since a half-open circuit is specifically *permitting*
    one probe call through — treating it as ineligible would prevent the
    probe that could close the circuit again from ever happening.
    """

    descriptor: AgentDescriptor
    status: AgentStatus
    circuit_state: CircuitState


__all__ = ["CandidateAgent"]
