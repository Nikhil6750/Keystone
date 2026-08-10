"""Bridge connecting Stage 8C.3A ConnectedAgent Repository to Router candidate descriptors.

Translates `ConnectedAgent` entities backed by active `AgentConnection` records
into `AgentDescriptor` maps for `RegistryCandidateProvider` and `Router`.

Preserves exact Router authority: candidate agent filtering, capability checks,
and circuit breaker availability evaluate normally. Prevents user metadata
from overwriting reserved bridge metadata keys.
"""

from app.contracts.adapter import AgentDescriptor
from app.contracts.enums import RuntimeKind
from app.engine.connections.models import AgentConnectionStatus, ConnectionKind
from app.engine.connections.repository import AgentConnectionRepository, ConnectedAgentRepository


class ConnectedAgentCandidateBridge:
    """Produces `AgentDescriptor` dictionaries for `RegistryCandidateProvider`."""

    def __init__(
        self,
        connection_repo: AgentConnectionRepository,
        agent_repo: ConnectedAgentRepository,
    ) -> None:
        self.connection_repo = connection_repo
        self.agent_repo = agent_repo

    def get_descriptors(self) -> dict[str, AgentDescriptor]:
        """Returns a mapping of agent_id -> AgentDescriptor for all enabled agents
        whose parent connection status is CONNECTED."""
        descriptors: dict[str, AgentDescriptor] = {}
        for agent in self.agent_repo.list(enabled_only=True):
            conn = self.connection_repo.get(agent.connection_id)
            if conn is None or conn.status != AgentConnectionStatus.CONNECTED:
                continue

            runtime_kind = (
                RuntimeKind.MODEL_API
                if conn.connection_kind == ConnectionKind.API
                else RuntimeKind.LOCAL_MODEL
                if conn.connection_kind == ConnectionKind.LOCAL
                else RuntimeKind.AGENT_CLI
            )

            # Build authoritative system metadata
            metadata: dict[str, object] = {
                "connection_id": conn.connection_id,
                "provider_or_runtime": conn.provider_or_runtime,
                "connection_kind": str(conn.connection_kind),
            }
            if agent.model_id is not None:
                metadata["model_id"] = agent.model_id

            # Merge user metadata safely -- reserved bridge keys cannot be overwritten
            for key, val in agent.metadata.items():
                if key not in metadata:
                    metadata[key] = val

            descriptor = AgentDescriptor(
                agent_type=agent.agent_id,
                display_name=agent.display_name,
                runtime_kind=runtime_kind,
                capabilities=list(agent.capabilities),
                metadata=metadata,
            )
            descriptors[agent.agent_id] = descriptor
        return descriptors
