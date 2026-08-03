"""Agent availability API."""

from fastapi import APIRouter, Depends

from app.api.deps import get_executor_registry
from app.core.config import Settings, get_settings
from app.engine.registry import ExecutorRegistry
from app.schemas.agents import AgentAvailabilityListResponse
from app.services.agent_availability import list_agent_availability

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=AgentAvailabilityListResponse)
def get_agents(
    settings: Settings = Depends(get_settings),  # noqa: B008
    registry: ExecutorRegistry = Depends(get_executor_registry),  # noqa: B008
) -> AgentAvailabilityListResponse:
    """Report configuration/availability/registration status for all four agent types."""
    items = list_agent_availability(settings, registry)
    return AgentAvailabilityListResponse.model_validate({"items": items, "count": len(items)})
