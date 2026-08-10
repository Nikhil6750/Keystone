"""FastAPI routes for Stage 8C.3A Agent Connections & Connected Agents."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import (
    get_agent_connection_repository,
    get_connected_agent_repository,
)
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
)
from app.engine.connections.repository import (
    AgentConnectionRepository,
    ConnectedAgentRepository,
)

router = APIRouter(tags=["agent-connections"])


@router.post(
    "/agent-connections",
    response_model=AgentConnection,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new agent connection",
)
def create_agent_connection(
    data: AgentConnectionCreate,
    repo: AgentConnectionRepository = Depends(get_agent_connection_repository),  # noqa: B008
) -> AgentConnection:
    """Registers a new integration connection (installed runtime, API, local, custom)."""
    try:
        return repo.register(data)
    except DuplicateConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.get(
    "/agent-connections",
    response_model=list[AgentConnection],
    summary="List registered agent connections",
)
def list_agent_connections(
    repo: AgentConnectionRepository = Depends(get_agent_connection_repository),  # noqa: B008
) -> list[AgentConnection]:
    """Returns all registered agent connections in deterministic connection_id order."""
    return repo.list()


@router.get(
    "/agent-connections/{connection_id}",
    response_model=AgentConnection,
    summary="Get a registered agent connection",
)
def get_agent_connection(
    connection_id: str,
    repo: AgentConnectionRepository = Depends(get_agent_connection_repository),  # noqa: B008
) -> AgentConnection:
    """Retrieves an agent connection by connection_id."""
    conn = repo.get(connection_id)
    if conn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"AgentConnection '{connection_id}' not found",
        )
    return conn


@router.delete(
    "/agent-connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an agent connection",
)
def delete_agent_connection(
    connection_id: str,
    conn_repo: AgentConnectionRepository = Depends(get_agent_connection_repository),  # noqa: B008
    agent_repo: ConnectedAgentRepository = Depends(get_connected_agent_repository),  # noqa: B008
) -> None:
    """Deletes an agent connection. Rejects deletion if dependent ConnectedAgents exist."""
    try:
        conn_repo.delete(connection_id, agent_repo)
    except ConnectionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ConnectionHasDependentAgentsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.post(
    "/connected-agents",
    response_model=ConnectedAgent,
    status_code=status.HTTP_201_CREATED,
    summary="Register a connected agent identity",
)
def create_connected_agent(
    data: ConnectedAgentCreate,
    conn_repo: AgentConnectionRepository = Depends(get_agent_connection_repository),  # noqa: B008
    agent_repo: ConnectedAgentRepository = Depends(get_connected_agent_repository),  # noqa: B008
) -> ConnectedAgent:
    """Registers a new connected agent identity referencing a valid connection_id."""
    try:
        return agent_repo.register(data, conn_repo)
    except ConnectionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except DuplicateAgentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.get(
    "/connected-agents",
    response_model=list[ConnectedAgent],
    summary="List connected agent identities",
)
def list_connected_agents(
    connection_id: str | None = None,
    enabled_only: bool = False,
    agent_repo: ConnectedAgentRepository = Depends(get_connected_agent_repository),  # noqa: B008
) -> list[ConnectedAgent]:
    """Returns connected agent identities, optionally filtered by connection_id or enabled state."""
    return agent_repo.list(connection_id=connection_id, enabled_only=enabled_only)


@router.get(
    "/connected-agents/{agent_id}",
    response_model=ConnectedAgent,
    summary="Get a connected agent identity",
)
def get_connected_agent(
    agent_id: str,
    agent_repo: ConnectedAgentRepository = Depends(get_connected_agent_repository),  # noqa: B008
) -> ConnectedAgent:
    """Retrieves a connected agent identity by agent_id."""
    agent = agent_repo.get(agent_id)
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ConnectedAgent '{agent_id}' not found",
        )
    return agent


@router.patch(
    "/connected-agents/{agent_id}",
    response_model=ConnectedAgent,
    summary="Update a connected agent identity",
)
def update_connected_agent(
    agent_id: str,
    data: ConnectedAgentUpdate,
    agent_repo: ConnectedAgentRepository = Depends(get_connected_agent_repository),  # noqa: B008
) -> ConnectedAgent:
    """Updates fields on an existing connected agent identity."""
    try:
        return agent_repo.update(agent_id, data)
    except AgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.delete(
    "/connected-agents/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a connected agent identity",
)
def delete_connected_agent(
    agent_id: str,
    agent_repo: ConnectedAgentRepository = Depends(get_connected_agent_repository),  # noqa: B008
) -> None:
    """Deletes a connected agent identity."""
    try:
        agent_repo.delete(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
