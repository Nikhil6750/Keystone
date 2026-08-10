"""Test-only helpers for Stage 8C.2 API/coordinator tests.

Builds a `ServiceFactory` (`app.engine.orchestration.execution`) using only
certified Stage 8A/8C.1 fakes/test doubles (`RecordingExecutor`) plus one
small new echoing fake manager -- nothing here makes a network call, reads
a credential, or launches a subprocess.

`EchoingFakeManagerModel` exists (rather than reusing `FakeManagerModel`
directly) because `ManagerProposalValidator` requires
`response.request_id == request.request_id`
(`app/engine/manager/validation.py`), and the API layer generates a fresh
`execution_id`/`request_id` per `POST` -- a single static `ManagerResponse`
cannot satisfy that check across more than one execution. Still fully
deterministic and offline: it only ever echoes the incoming request's own
`request_id` back, never invents one.

Candidates are built via `StaticCandidateProvider` with a locally-built
`AgentDescriptor` advertising every `AgentCapability` (mirroring the same
pattern already live-verified for Stage 8C.1's own dynamic-agent smoke
test) -- this avoids needing a populated `AgentConnectionCache` just to
mark a test's dynamic agent `AVAILABLE`.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.contracts.adapter import AgentDescriptor
from app.contracts.enums import AgentCapability, AgentStatus, RuntimeKind
from app.engine.manager.models import ManagerRequest, ManagerResponse, ManagerTaskProposal
from app.engine.orchestration.events import OrchestrationEventSequence, OrchestrationEventSink
from app.engine.orchestration.execution import ServiceFactory
from app.engine.orchestration.models import OrchestrationRequest
from app.engine.orchestration.runtime import StaticCandidateProvider
from app.engine.orchestration.service import EndToEndOrchestrationService
from app.engine.registry import ExecutorRegistry
from app.engine.routing.availability import CandidateAgent
from app.resilience.circuit_breaker import CircuitBreakerRegistry, CircuitState
from app.resilience.retry import RetryPolicy
from tests.support.executors import RecordingExecutor


@dataclass
class EchoingFakeManagerModel:
    """A deterministic `ManagerModel` test double that echoes the
    incoming request's own `request_id` into its response (see module
    docstring for why). No network, no randomness."""

    agent_type: str
    provider_identifier: str = "fake-manager-api-test"
    calls: list[ManagerRequest] = field(default_factory=list)

    def identifier(self) -> str:
        return self.provider_identifier

    async def propose(self, request: ManagerRequest) -> ManagerResponse:
        self.calls.append(request)
        return ManagerResponse(
            request_id=request.request_id,
            provider_identifier=self.provider_identifier,
            task_proposals=[
                ManagerTaskProposal(
                    key="t1",
                    description="implement the requested change",
                    preferred_agent_types=[self.agent_type],
                )
            ],
        )


def build_test_service_factory(
    *,
    db_engine: Engine,
    agent_type: str,
    executor: RecordingExecutor | None = None,
) -> tuple[ServiceFactory, EchoingFakeManagerModel, ExecutorRegistry]:
    """Returns `(service_factory, manager, registry)`.

    `manager.calls` lets a test assert exactly-once Manager invocation
    across an execution's whole lifetime (including any SSE reconnects --
    Part 16/17). `registry` is exposed so a test can additionally assert
    only the caller-chosen dynamic `agent_type` was ever registered --
    never a fixed Claude/Codex/Gemini identity.
    """
    session_factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    registry = ExecutorRegistry()
    registry.register(agent_type, executor or RecordingExecutor())
    manager = EchoingFakeManagerModel(agent_type=agent_type)
    circuit_breakers = CircuitBreakerRegistry(failure_threshold=3, recovery_timeout_seconds=30.0)
    retry_policy = RetryPolicy(base_delay_seconds=0.01, max_delay_seconds=0.05, jitter_ratio=0.0)

    descriptor = AgentDescriptor(
        agent_type=agent_type,
        display_name=f"Dynamic test agent ({agent_type})",
        runtime_kind=RuntimeKind.AGENT_CLI,
        capabilities=list(AgentCapability),
    )
    candidate = CandidateAgent(
        descriptor=descriptor, status=AgentStatus.AVAILABLE, circuit_state=CircuitState.CLOSED
    )
    candidate_provider = StaticCandidateProvider(agents=(candidate,))

    def factory(
        request: OrchestrationRequest,
        event_sink: OrchestrationEventSink,
        event_sequence: OrchestrationEventSequence,
    ) -> tuple[EndToEndOrchestrationService, Callable[[], None]]:
        db = session_factory()
        service = EndToEndOrchestrationService(
            db=db,
            registry=registry,
            candidate_provider=candidate_provider,
            manager_model=manager,
            circuit_breakers=circuit_breakers,
            retry_policy=retry_policy,
            event_sink=event_sink,
            event_sequence=event_sequence,
        )
        return service, db.close

    return factory, manager, registry


__all__ = ["EchoingFakeManagerModel", "build_test_service_factory"]
