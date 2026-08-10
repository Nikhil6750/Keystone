"""Repositories for AgentConnection and ConnectedAgent entities.

Storage-neutral, thread-safe in-memory implementations satisfying Stage 8C.3A
referential integrity guarantees. No database migrations introduced.
"""

from threading import RLock

from app.engine.connections.exceptions import (
    AgentNotFoundError,
    ConnectionHasDependentAgentsError,
    ConnectionNotFoundError,
    DuplicateAgentError,
    DuplicateConnectionError,
)
from app.engine.connections.models import (
    AgentConnection,
    AgentConnectionCreate,
    ConnectedAgent,
    ConnectedAgentCreate,
    ConnectedAgentUpdate,
    utc_now,
)


class AgentConnectionRepository:
    """Repository storing `AgentConnection` entities."""

    def __init__(self) -> None:
        self._connections: dict[str, AgentConnection] = {}
        self._lock = RLock()

    def register(self, payload: AgentConnectionCreate | AgentConnection) -> AgentConnection:
        with self._lock:
            cid = payload.connection_id.strip()
            if cid in self._connections:
                raise DuplicateConnectionError(cid)

            if isinstance(payload, AgentConnection):
                conn = payload
            else:
                conn = AgentConnection(
                    connection_id=cid,
                    display_name=payload.display_name,
                    connection_kind=payload.connection_kind,
                    provider_or_runtime=payload.provider_or_runtime,
                    status=payload.status,
                    metadata=dict(payload.metadata),
                )

            self._connections[cid] = conn
            return conn

    def get(self, connection_id: str) -> AgentConnection | None:
        with self._lock:
            return self._connections.get(connection_id.strip())

    def list(self) -> list[AgentConnection]:
        with self._lock:
            return sorted(self._connections.values(), key=lambda c: c.connection_id)

    def delete(
        self, connection_id: str, agent_repo: "ConnectedAgentRepository"
    ) -> bool:
        with self._lock:
            cid = connection_id.strip()
            if cid not in self._connections:
                raise ConnectionNotFoundError(cid)

            dependent_agents = agent_repo.list(connection_id=cid)
            if dependent_agents:
                raise ConnectionHasDependentAgentsError(
                    cid, [a.agent_id for a in dependent_agents]
                )

            del self._connections[cid]
            return True


class ConnectedAgentRepository:
    """Repository storing `ConnectedAgent` entities with connection FK enforcement."""

    def __init__(self) -> None:
        self._agents: dict[str, ConnectedAgent] = {}
        self._lock = RLock()

    def register(
        self,
        payload: ConnectedAgentCreate | ConnectedAgent,
        connection_repo: AgentConnectionRepository,
    ) -> ConnectedAgent:
        with self._lock:
            aid = payload.agent_id.strip()
            cid = payload.connection_id.strip()

            if connection_repo.get(cid) is None:
                raise ConnectionNotFoundError(cid)

            if aid in self._agents:
                raise DuplicateAgentError(aid)

            if isinstance(payload, ConnectedAgent):
                agent = payload
            else:
                agent = ConnectedAgent(
                    agent_id=aid,
                    display_name=payload.display_name,
                    connection_id=cid,
                    model_id=payload.model_id,
                    capabilities=list(payload.capabilities),
                    enabled=payload.enabled,
                    metadata=dict(payload.metadata),
                )

            self._agents[aid] = agent
            return agent

    def get(self, agent_id: str) -> ConnectedAgent | None:
        with self._lock:
            return self._agents.get(agent_id.strip())

    def list(
        self, connection_id: str | None = None, enabled_only: bool = False
    ) -> list[ConnectedAgent]:
        with self._lock:
            result = list(self._agents.values())
            if connection_id is not None:
                cid = connection_id.strip()
                result = [a for a in result if a.connection_id == cid]
            if enabled_only:
                result = [a for a in result if a.enabled]
            return sorted(result, key=lambda a: a.agent_id)

    def update(
        self, agent_id: str, updates: ConnectedAgentUpdate
    ) -> ConnectedAgent:
        with self._lock:
            aid = agent_id.strip()
            existing = self._agents.get(aid)
            if existing is None:
                raise AgentNotFoundError(aid)

            updated_data = existing.model_dump()
            if updates.display_name is not None:
                updated_data["display_name"] = updates.display_name
            if updates.model_id is not None:
                updated_data["model_id"] = updates.model_id
            if updates.capabilities is not None:
                updated_data["capabilities"] = list(updates.capabilities)
            if updates.enabled is not None:
                updated_data["enabled"] = updates.enabled
            if updates.metadata is not None:
                updated_data["metadata"] = dict(updates.metadata)
            updated_data["updated_at"] = utc_now()

            updated_agent = ConnectedAgent.model_validate(updated_data)
            self._agents[aid] = updated_agent
            return updated_agent

    def delete(self, agent_id: str) -> bool:
        with self._lock:
            aid = agent_id.strip()
            if aid not in self._agents:
                raise AgentNotFoundError(aid)
            del self._agents[aid]
            return True
