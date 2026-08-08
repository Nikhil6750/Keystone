"""What the router needs to know about one candidate agent's current live
state, independent of its historical performance evidence.

Callers assemble `CandidateAgent`s from whatever they already have —
`app.adapters.connection.AgentConnectionCache` for installation/auth/
connection status (collapsed here to the coarser `AgentStatus`, see
`app.contracts.enums`) and `app.resilience.circuit_breaker
.CircuitBreakerRegistry` for circuit state — the router itself has no
dependency on either.
"""

from dataclasses import dataclass

from app.contracts.adapter import AgentDescriptor
from app.contracts.enums import AgentStatus
from app.resilience.circuit_breaker import CircuitState


@dataclass(frozen=True)
class CandidateAgent:
    """One agent the router may consider, with its current live status."""

    descriptor: AgentDescriptor
    status: AgentStatus
    circuit_state: CircuitState


__all__ = ["CandidateAgent"]
