"""Agent availability and connection-verification API."""

from fastapi import APIRouter, Depends

from app.adapters.connection import AgentConnectionCache
from app.api.deps import get_agent_connection_cache, get_executor_registry
from app.core.config import Settings, get_settings
from app.engine.registry import ExecutorRegistry
from app.schemas.agents import AgentAvailabilityListResponse, AgentConnectionVerifyRead
from app.services.agent_availability import list_agent_availability
from app.services.agent_connection import verify_agent

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=AgentAvailabilityListResponse)
def get_agents(
    settings: Settings = Depends(get_settings),  # noqa: B008
    registry: ExecutorRegistry = Depends(get_executor_registry),  # noqa: B008
    cache: AgentConnectionCache = Depends(get_agent_connection_cache),  # noqa: B008
) -> AgentAvailabilityListResponse:
    """Report configuration/availability/connection status for every canonical agent type.

    Always returns instantly from cached/last-known connection state — never
    performs a live verification call itself (see `.../verify` below).
    """
    items = list_agent_availability(settings, registry, cache)
    return AgentAvailabilityListResponse.model_validate({"items": items, "count": len(items)})


@router.post("/{agent_type}/verify", response_model=AgentConnectionVerifyRead)
def verify_agent_connection(
    agent_type: str,
    settings: Settings = Depends(get_settings),  # noqa: B008
    registry: ExecutorRegistry = Depends(get_executor_registry),  # noqa: B008
    cache: AgentConnectionCache = Depends(get_agent_connection_cache),  # noqa: B008
) -> AgentConnectionVerifyRead:
    """Run one safe, backend-owned headless verification for `agent_type`.

    Never accepts a prompt from the caller. Raises `404 AGENT_TYPE_UNKNOWN`
    for a non-canonical agent type, and `409 AGENT_VERIFICATION_IN_PROGRESS`
    if a verification for the same agent type is already running.
    """
    state = verify_agent(agent_type, settings, registry, cache)
    return AgentConnectionVerifyRead.model_validate(state)
