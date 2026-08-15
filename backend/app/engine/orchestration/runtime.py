"""Assembles `CandidateAgent`s (`app.engine.routing.availability`) for the
Router.

`CandidateAgent`'s own docstring is explicit: *"Callers assemble
`CandidateAgent`s from whatever they already have."* Architecture
discovery for Stage 8C.1 confirmed no production code path did this before
now -- every existing construction site was a test file. This module is
that first real caller, via the `RuntimeCandidateProvider` Protocol so the
orchestration service never depends on a concrete source (Part 5:
testable without real runtimes/network).

`RegistryCandidateProvider` reads only already-existing, already-owned
state: whether each candidate `agent_type` actually has an executor
registered in the live `ExecutorRegistry` (`app.engine.registry`, owned by
Developer 3's connector-registration code, e.g.
`app.adapters.factory.register_agents` -- this module never registers or
constructs an adapter itself, and never enumerates the registry's private
internals -- `ExecutorRegistry` exposes no listing method by design, so
the candidate agent-type set is always caller-supplied, never guessed),
their cached connection status via `AgentConnectionCache`
(`app.adapters.connection`, read-only lookup, never a live verification
call -- see `app.services.agent_connection.verify_agent` for the one place
that performs one), and circuit-breaker state via `CircuitBreakerRegistry`
(`app.resilience.circuit_breaker`). The static `AgentDescriptor` per agent
type (display name, capabilities) is caller-supplied at construction,
never invented here -- see `STATIC_AGENT_DESCRIPTORS` for the descriptors
this codebase's own `app.adapters.types.AgentType` enum already implies.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from app.adapters.connection import AgentConnectionCache, ConnectionStatus
from app.adapters.types import AgentType
from app.contracts.adapter import AgentDescriptor
from app.contracts.enums import AgentCapability, AgentStatus, RuntimeKind
from app.engine.registry import ExecutorNotRegisteredError, ExecutorRegistry
from app.engine.routing.availability import CandidateAgent
from app.resilience.circuit_breaker import CircuitBreakerRegistry, CircuitState

# Static identity/capability declarations for this codebase's own known
# agent types (`app.adapters.types.AgentType`) -- descriptive metadata
# only, never a claim about live availability (that comes from
# `AgentConnectionCache`/`CircuitBreakerRegistry` at call time). A caller
# with different or additional agent types supplies its own descriptor map
# to `RegistryCandidateProvider` instead of relying on this default.
STATIC_AGENT_DESCRIPTORS: dict[str, AgentDescriptor] = {
    AgentType.CLAUDE_CODE.value: AgentDescriptor(
        agent_type=AgentType.CLAUDE_CODE.value,
        display_name="Claude Code",
        runtime_kind=RuntimeKind.AGENT_CLI,
        capabilities=[
            AgentCapability.CODE_GENERATION,
            AgentCapability.CODE_REVIEW,
            AgentCapability.DEBUGGING,
            AgentCapability.REFACTORING,
            AgentCapability.TEST_GENERATION,
            AgentCapability.FILE_EDITING,
            # Claude Code is a full agentic coding CLI: it can run a test
            # suite as part of its own tool use (`pytest`, `npm test`, ...)
            # and reason generally about a goal, not just generate code --
            # both were previously missing from this declaration, which
            # made ordinary "implement + verify" and testing-category plan
            # templates (`app.engine.planning.templates`, both of which
            # require `TEST_EXECUTION`) permanently unroutable to it
            # regardless of connection status. Purely additive: never
            # removes a capability, so it can only make more tasks
            # routable, never fewer.
            AgentCapability.GENERAL_REASONING,
            AgentCapability.TEST_EXECUTION,
            AgentCapability.PLANNING,
            AgentCapability.DOCUMENTATION,
        ],
    ),
    AgentType.CODEX.value: AgentDescriptor(
        agent_type=AgentType.CODEX.value,
        display_name="Codex",
        runtime_kind=RuntimeKind.AGENT_CLI,
        capabilities=[
            AgentCapability.CODE_GENERATION,
            AgentCapability.CODE_REVIEW,
            AgentCapability.DEBUGGING,
            AgentCapability.REFACTORING,
            AgentCapability.TEST_GENERATION,
            AgentCapability.FILE_EDITING,
            AgentCapability.GENERAL_REASONING,
            AgentCapability.TEST_EXECUTION,
            AgentCapability.PLANNING,
            AgentCapability.DOCUMENTATION,
        ],
    ),
    AgentType.GEMINI.value: AgentDescriptor(
        agent_type=AgentType.GEMINI.value,
        display_name="Gemini CLI",
        runtime_kind=RuntimeKind.AGENT_CLI,
        capabilities=[AgentCapability.CODE_GENERATION, AgentCapability.GENERAL_REASONING],
    ),
    AgentType.ANTIGRAVITY.value: AgentDescriptor(
        agent_type=AgentType.ANTIGRAVITY.value,
        display_name="Antigravity",
        runtime_kind=RuntimeKind.AGENT_CLI,
        capabilities=[
            AgentCapability.CODE_GENERATION,
            AgentCapability.CODE_REVIEW,
            AgentCapability.DEBUGGING,
            AgentCapability.REFACTORING,
            AgentCapability.TEST_GENERATION,
            AgentCapability.FILE_EDITING,
            AgentCapability.GENERAL_REASONING,
            AgentCapability.TEST_EXECUTION,
            AgentCapability.PLANNING,
            AgentCapability.DOCUMENTATION,
        ],
    ),
    AgentType.DEMO.value: AgentDescriptor(
        agent_type=AgentType.DEMO.value,
        display_name="Demo Agent",
        runtime_kind=RuntimeKind.AGENT_CLI,
        # `DemoAgentAdapter.execute()` always returns the same canned,
        # clearly-labeled "[DEMO] Simulated result" regardless of what
        # capability a task actually needed (see app/adapters/demo.py) --
        # unlike the real CLI adapters above, declaring a broader
        # capability set here never overclaims what it can *do*, only
        # what task shapes the Router will consider routing to it. A
        # narrower set (previously just CODE_GENERATION and
        # GENERAL_REASONING, mirroring Gemini's real, genuinely limited
        # capabilities) made the demo agent permanently unroutable for the
        # ordinary "implement + test" task graphs the real Planner
        # generates for most goals -- defeating its purpose as the
        # no-cost, no-external-dependency local E2E path (same rationale
        # already applied to Claude Code's own capability list above).
        capabilities=[
            AgentCapability.CODE_GENERATION,
            AgentCapability.CODE_REVIEW,
            AgentCapability.DEBUGGING,
            AgentCapability.REFACTORING,
            AgentCapability.TEST_GENERATION,
            AgentCapability.FILE_EDITING,
            AgentCapability.GENERAL_REASONING,
            AgentCapability.TEST_EXECUTION,
            AgentCapability.PLANNING,
            AgentCapability.DOCUMENTATION,
        ],
    ),
}

# `AgentConnectionState.connection_status` -> `AgentStatus`. `CONNECTED` is
# the only value a recent, real headless verification produces (see
# `app.adapters.connection`'s module docstring) -- everything else,
# including "not yet checked," maps to something less than `AVAILABLE`,
# never silently upgraded.
_CONNECTION_STATUS_TO_AGENT_STATUS: dict[ConnectionStatus, AgentStatus] = {
    ConnectionStatus.CONNECTED: AgentStatus.AVAILABLE,
    ConnectionStatus.VERIFICATION_REQUIRED: AgentStatus.UNKNOWN,
    ConnectionStatus.VERIFICATION_FAILED: AgentStatus.UNAVAILABLE,
    ConnectionStatus.UNAVAILABLE: AgentStatus.UNAVAILABLE,
    ConnectionStatus.DISABLED: AgentStatus.UNAVAILABLE,
}


class RuntimeCandidateProvider(Protocol):
    """The Router's runtime-candidate source -- the orchestration
    service's dependency-injection seam for "what agents can I use right
    now." A test supplies a static/fake list; production supplies
    `RegistryCandidateProvider`."""

    def candidates(self) -> list[CandidateAgent]: ...


@dataclass(frozen=True)
class StaticCandidateProvider:
    """A fixed, caller-supplied `CandidateAgent` list -- for tests and for
    any deployment that wants to bypass live registry/connection-cache
    lookups entirely. No network, no CLI, no registry access."""

    agents: tuple[CandidateAgent, ...]

    def candidates(self) -> list[CandidateAgent]:
        return list(self.agents)


@dataclass(frozen=True)
class RegistryCandidateProvider:
    """Builds `CandidateAgent`s for a caller-declared set of `agent_types`,
    keeping only the ones actually registered in the live
    `ExecutorRegistry`, enriched with optional cached connection/circuit-
    breaker state. Never performs a live CLI check or network call itself
    -- it only reads state those other, already-owned components already
    maintain, and never enumerates the registry's internals (it has no
    listing method by design)."""

    registry: ExecutorRegistry
    agent_types: tuple[str, ...]
    descriptors: dict[str, AgentDescriptor] | None = None
    connection_cache: AgentConnectionCache | None = None
    circuit_breakers: CircuitBreakerRegistry | None = None

    def candidates(self) -> list[CandidateAgent]:
        descriptors = self.descriptors if self.descriptors is not None else STATIC_AGENT_DESCRIPTORS
        result: list[CandidateAgent] = []
        for agent_type in sorted(set(self.agent_types)):
            if not self._is_registered(agent_type):
                continue
            descriptor = descriptors.get(agent_type)
            if descriptor is None:
                # A registered executor with no known static descriptor
                # cannot be safely routed -- skip rather than fabricate
                # capabilities/display metadata for it.
                continue
            # A dynamic Connect-Agent identity (e.g. "claude-work") is
            # usually not itself the key the connection cache or circuit
            # breaker were populated/tripped under -- `POST
            # /agents/{agent_type}/verify` and `.../runtime-connections/
            # {runtime_id}/activate` both only ever know the canonical
            # runtime name ("claude_code"). `ConnectedAgentCandidateBridge`
            # already stamps that canonical name into `descriptor.metadata
            # ["provider_or_runtime"]`, so fall back to it -- checked only
            # second, after the agent's own id -- instead of leaving every
            # dynamic agent stuck at `AgentStatus.UNKNOWN` (ineligible, see
            # `scorer.eligibility_violation`) forever.
            fallback_key = descriptor.metadata.get("provider_or_runtime")
            result.append(
                CandidateAgent(
                    descriptor=descriptor,
                    status=self._status_for(agent_type, fallback_key),
                    circuit_state=self._circuit_state_for(agent_type, fallback_key),
                )
            )
        return result

    def _is_registered(self, agent_type: str) -> bool:
        try:
            self.registry.get(agent_type)
        except ExecutorNotRegisteredError:
            return False
        return True

    def _status_for(self, agent_type: str, fallback_key: object) -> AgentStatus:
        if self.connection_cache is None:
            return AgentStatus.UNKNOWN
        state = self.connection_cache.get(agent_type)
        if state is None and fallback_key is not None:
            state = self.connection_cache.get(str(fallback_key))
        if state is None:
            return AgentStatus.UNKNOWN
        return _CONNECTION_STATUS_TO_AGENT_STATUS.get(state.connection_status, AgentStatus.UNKNOWN)

    def _circuit_state_for(self, agent_type: str, fallback_key: object) -> CircuitState:
        if self.circuit_breakers is None:
            return CircuitState.CLOSED
        # Unlike connection status, a circuit breaker always tracks the
        # shared underlying process (every dynamic agent aliased onto the
        # same runtime trips and recovers together), so the canonical key
        # -- when known -- is authoritative, not just a fallback.
        key = str(fallback_key) if fallback_key is not None else agent_type
        return self.circuit_breakers.get_or_create(key).snapshot().state


def default_candidate_agent_types() -> Iterable[str]:
    """The agent types `STATIC_AGENT_DESCRIPTORS` knows about, for a caller
    that has not declared its own candidate set explicitly."""
    return STATIC_AGENT_DESCRIPTORS.keys()


__all__ = [
    "STATIC_AGENT_DESCRIPTORS",
    "RegistryCandidateProvider",
    "RuntimeCandidateProvider",
    "StaticCandidateProvider",
    "default_candidate_agent_types",
]
