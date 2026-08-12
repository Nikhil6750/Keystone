"""Repositories for AgentConnection and ConnectedAgent entities.

Storage-neutral, thread-safe in-memory implementations satisfying Stage 8C.3A
referential integrity guarantees. Shares a single synchronization lock across
repositories to guarantee AB-BA deadlock prevention. Defensive deep copies
on both write and read operations eliminate nested container mutation leaks.
"""

from threading import RLock
from typing import Any

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
    AgentConnectionUpdate,
    ConnectedAgent,
    ConnectedAgentCreate,
    ConnectedAgentUpdate,
    utc_now,
)


class ConnectionRegistryCoordinator:
    """Shared synchronization coordinator for AgentConnection and ConnectedAgent repositories."""

    def __init__(self, lock: Any | None = None) -> None:
        self.lock = lock or RLock()


class AgentConnectionRepository:
    """Repository storing `AgentConnection` entities with deep-copy state isolation."""

    def __init__(self, coordinator: ConnectionRegistryCoordinator | None = None) -> None:
        self._coordinator = coordinator or ConnectionRegistryCoordinator()
        self._connections: dict[str, AgentConnection] = {}

    @property
    def coordinator(self) -> ConnectionRegistryCoordinator:
        return self._coordinator

    def register(
        self, payload: AgentConnectionCreate | AgentConnection
    ) -> AgentConnection:
        with self._coordinator.lock:
            cid = payload.connection_id.strip()
            if cid in self._connections:
                raise DuplicateConnectionError(cid)

            if isinstance(payload, AgentConnection):
                conn = payload.model_copy(deep=True)
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
            return conn.model_copy(deep=True)

    def get(self, connection_id: str) -> AgentConnection | None:
        with self._coordinator.lock:
            conn = self._connections.get(connection_id.strip())
            if conn is None:
                return None
            return conn.model_copy(deep=True)

    def list(self) -> list[AgentConnection]:
        with self._coordinator.lock:
            ordered = sorted(self._connections.values(), key=lambda c: c.connection_id)
            return [c.model_copy(deep=True) for c in ordered]

    def update(
        self, connection_id: str, updates: AgentConnectionUpdate
    ) -> AgentConnection:
        with self._coordinator.lock:
            cid = connection_id.strip()
            existing = self._connections.get(cid)
            if existing is None:
                raise ConnectionNotFoundError(cid)

            new_display = (
                updates.display_name
                if updates.display_name is not None
                else existing.display_name
            )
            new_status = (
                updates.status if updates.status is not None else existing.status
            )
            new_meta = (
                dict(updates.metadata)
                if updates.metadata is not None
                else dict(existing.metadata)
            )

            updated_conn = AgentConnection(
                connection_id=existing.connection_id,
                display_name=new_display,
                connection_kind=existing.connection_kind,
                provider_or_runtime=existing.provider_or_runtime,
                status=new_status,
                metadata=new_meta,
                created_at=existing.created_at,
                updated_at=utc_now(),
            )
            self._connections[cid] = updated_conn
            return updated_conn.model_copy(deep=True)

    def delete(
        self, connection_id: str, agent_repo: "ConnectedAgentRepository"
    ) -> bool:
        with self._coordinator.lock:
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
    """Repository storing `ConnectedAgent` entities with deep-copy state isolation."""

    def __init__(self, coordinator: ConnectionRegistryCoordinator | None = None) -> None:
        self._coordinator = coordinator or ConnectionRegistryCoordinator()
        self._agents: dict[str, ConnectedAgent] = {}

    @property
    def coordinator(self) -> ConnectionRegistryCoordinator:
        return self._coordinator

    def register(
        self,
        payload: ConnectedAgentCreate | ConnectedAgent,
        connection_repo: AgentConnectionRepository,
    ) -> ConnectedAgent:
        with self._coordinator.lock:
            aid = payload.agent_id.strip()
            cid = payload.connection_id.strip()

            parent_conn = connection_repo.get(cid)
            if parent_conn is None:
                raise ConnectionNotFoundError(cid)

            if aid in self._agents:
                raise DuplicateAgentError(aid)

            if isinstance(payload, ConnectedAgent):
                agent = payload.model_copy(deep=True)
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
            return agent.model_copy(deep=True)

    def get(self, agent_id: str) -> ConnectedAgent | None:
        with self._coordinator.lock:
            agent = self._agents.get(agent_id.strip())
            if agent is None:
                return None
            return agent.model_copy(deep=True)

    def list(
        self, connection_id: str | None = None, enabled_only: bool = False
    ) -> list[ConnectedAgent]:
        with self._coordinator.lock:
            result = list(self._agents.values())
            if connection_id is not None:
                cid = connection_id.strip()
                result = [a for a in result if a.connection_id == cid]
            if enabled_only:
                result = [a for a in result if a.enabled]
            ordered = sorted(result, key=lambda a: a.agent_id)
            return [a.model_copy(deep=True) for a in ordered]

    def update(
        self, agent_id: str, updates: ConnectedAgentUpdate
    ) -> ConnectedAgent:
        with self._coordinator.lock:
            aid = agent_id.strip()
            existing = self._agents.get(aid)
            if existing is None:
                raise AgentNotFoundError(aid)

            new_display = (
                updates.display_name
                if updates.display_name is not None
                else existing.display_name
            )
            new_model = (
                updates.model_id
                if updates.model_id is not None
                else existing.model_id
            )
            new_caps = (
                list(updates.capabilities)
                if updates.capabilities is not None
                else list(existing.capabilities)
            )
            new_enabled = (
                updates.enabled if updates.enabled is not None else existing.enabled
            )
            new_meta = (
                dict(updates.metadata)
                if updates.metadata is not None
                else dict(existing.metadata)
            )

            updated_agent = ConnectedAgent(
                agent_id=existing.agent_id,
                display_name=new_display,
                connection_id=existing.connection_id,
                model_id=new_model,
                capabilities=new_caps,
                enabled=new_enabled,
                metadata=new_meta,
                created_at=existing.created_at,
                updated_at=utc_now(),
            )
            self._agents[aid] = updated_agent
            return updated_agent.model_copy(deep=True)

    def delete(self, agent_id: str) -> bool:
        with self._coordinator.lock:
            aid = agent_id.strip()
            if aid not in self._agents:
                raise AgentNotFoundError(aid)
            del self._agents[aid]
            return True
