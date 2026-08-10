"""Exceptions for Stage 8C.3A Agent Connections."""


class AgentConnectionError(Exception):
    """Base exception for agent connection operations."""


class DuplicateConnectionError(AgentConnectionError):
    """Raised when registering an AgentConnection with an already-existing connection_id."""

    def __init__(self, connection_id: str) -> None:
        self.connection_id = connection_id
        super().__init__(f"AgentConnection '{connection_id}' is already registered")


class ConnectionNotFoundError(AgentConnectionError):
    """Raised when looking up or updating a nonexistent connection_id."""

    def __init__(self, connection_id: str) -> None:
        self.connection_id = connection_id
        super().__init__(f"AgentConnection '{connection_id}' not found")


class ConnectionHasDependentAgentsError(AgentConnectionError):
    """Raised when trying to delete an AgentConnection that still has dependent ConnectedAgents."""

    def __init__(self, connection_id: str, dependent_agent_ids: list[str]) -> None:
        self.connection_id = connection_id
        self.dependent_agent_ids = dependent_agent_ids
        super().__init__(
            f"Cannot delete AgentConnection '{connection_id}' because dependent agents "
            f"exist: {dependent_agent_ids}"
        )


class DuplicateAgentError(AgentConnectionError):
    """Raised when registering a ConnectedAgent with an already-existing agent_id."""

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        super().__init__(f"ConnectedAgent '{agent_id}' is already registered")


class AgentNotFoundError(AgentConnectionError):
    """Raised when looking up or updating a nonexistent agent_id."""

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        super().__init__(f"ConnectedAgent '{agent_id}' not found")
