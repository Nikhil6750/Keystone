"""Stage 8C.3A Agent Connections Module."""

from app.engine.connections.bridge import ConnectedAgentCandidateBridge
from app.engine.connections.exceptions import (
    AgentConnectionError,
    AgentNotFoundError,
    ConnectionHasDependentAgentsError,
    ConnectionNotFoundError,
    DuplicateAgentError,
    DuplicateConnectionError,
)
from app.engine.connections.models import (
    AgentConnection,
    AgentConnectionCreate,
    AgentConnectionStatus,
    AgentConnectionUpdate,
    ConnectedAgent,
    ConnectedAgentCreate,
    ConnectedAgentUpdate,
    ConnectionKind,
)
from app.engine.connections.repository import (
    AgentConnectionRepository,
    ConnectedAgentRepository,
    ConnectionRegistryCoordinator,
)

__all__ = [
    "AgentConnection",
    "AgentConnectionCreate",
    "AgentConnectionError",
    "AgentConnectionRepository",
    "AgentConnectionStatus",
    "AgentConnectionUpdate",
    "AgentNotFoundError",
    "ConnectedAgent",
    "ConnectedAgentCandidateBridge",
    "ConnectedAgentCreate",
    "ConnectedAgentRepository",
    "ConnectedAgentUpdate",
    "ConnectionHasDependentAgentsError",
    "ConnectionKind",
    "ConnectionNotFoundError",
    "ConnectionRegistryCoordinator",
    "DuplicateAgentError",
    "DuplicateConnectionError",
]
