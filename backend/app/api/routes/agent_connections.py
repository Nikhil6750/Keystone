"""FastAPI routes for Stage 8C.3A Agent Connections & Connected Agents."""

import logging

from fastapi import APIRouter, Depends, status

from app.api.deps import (
    get_agent_connection_repository,
    get_connected_agent_repository,
    get_executor_registry,
)
from app.engine.connections.exceptions import (
    AgentNotFoundError,
    ConnectionNotFoundError,
)
from app.engine.connections.models import (
    AgentConnection,
    AgentConnectionCreate,
    AgentConnectionUpdate,
    ConnectedAgent,
    ConnectedAgentCreate,
    ConnectedAgentUpdate,
    ConnectionKind,
)
from app.engine.connections.repository import (
    AgentConnectionRepository,
    ConnectedAgentRepository,
)
from app.engine.registry import ExecutorNotRegisteredError, ExecutorRegistry

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent-connections"])


def _alias_executor_for_installed_runtime_agent(
    agent: ConnectedAgent,
    conn: AgentConnection,
    registry: ExecutorRegistry,
) -> None:
    """For an `installed_runtime` connection whose underlying
    `provider_or_runtime` already has a live executor registered (via
    startup config or `POST /runtime-connections/{id}/activate`), makes
    that same executor instance reachable under the new agent's own
    `agent_id` too.

    This is the one missing link between "a ConnectedAgent identity exists"
    and "the Router can actually route to it": `ExecutorRegistry` is keyed
    by whatever string the caller asks for, and the orchestration engine
    looks up `registry.get(selected_agent_type)` using the *agent's* id
    (`app.engine.workflow_engine`), not the canonical runtime name -- so
    without this alias, a dynamic agent like `claude-work` would never be
    executable even though `claude_code` itself is registered. A missing
    or not-yet-activated runtime is not an error here: the agent identity
    still gets created (Connection != Agent), it just is not yet
    executable, exactly like every other connection kind without a live
    executor.
    """
    if conn.connection_kind != ConnectionKind.INSTALLED_RUNTIME:
        return
    try:
        underlying_executor = registry.get(conn.provider_or_runtime)
    except ExecutorNotRegisteredError:
        logger.info(
            "connected_agent_executor_alias_skipped agent_id=%s provider_or_runtime=%s "
            "reason=runtime_not_activated",
            agent.agent_id,
            conn.provider_or_runtime,
        )
        return
    registry.register(agent.agent_id, underlying_executor, replace=True)
    logger.info(
        "connected_agent_executor_aliased agent_id=%s provider_or_runtime=%s",
        agent.agent_id,
        conn.provider_or_runtime,
    )


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
    return repo.register(data)


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
        raise ConnectionNotFoundError(connection_id)
    return conn


@router.patch(
    "/agent-connections/{connection_id}",
    response_model=AgentConnection,
    summary="Update an agent connection",
)
def update_agent_connection(
    connection_id: str,
    data: AgentConnectionUpdate,
    repo: AgentConnectionRepository = Depends(get_agent_connection_repository),  # noqa: B008
) -> AgentConnection:
    """Updates mutable fields (display_name, status, metadata) on an agent connection."""
    return repo.update(connection_id, data)


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
    conn_repo.delete(connection_id, agent_repo)


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
    registry: ExecutorRegistry = Depends(get_executor_registry),  # noqa: B008
) -> ConnectedAgent:
    """Registers a new connected agent identity referencing a valid connection_id.

    For an `installed_runtime` connection whose runtime is already
    activated, also makes the agent immediately executable by the Router
    (see `_alias_executor_for_installed_runtime_agent`) -- otherwise the
    identity is still created, just not yet executable, same as any other
    connection kind.
    """
    agent = agent_repo.register(data, conn_repo)
    conn = conn_repo.get(agent.connection_id)
    if conn is not None:
        _alias_executor_for_installed_runtime_agent(agent, conn, registry)
    return agent


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
        raise AgentNotFoundError(agent_id)
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
    return agent_repo.update(agent_id, data)


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
    agent_repo.delete(agent_id)
