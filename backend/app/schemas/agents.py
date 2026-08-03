"""Schemas for the agent-availability API."""

from pydantic import BaseModel, ConfigDict


class AgentAvailabilityRead(BaseModel):
    """Serialized availability report for one canonical agent type."""

    model_config = ConfigDict(from_attributes=True)

    agent_type: str
    enabled: bool
    available: bool
    registered: bool
    execution_mode: str
    reason: str


class AgentAvailabilityListResponse(BaseModel):
    """Response envelope for `GET /api/v1/agents`."""

    model_config = ConfigDict(from_attributes=True)

    items: list[AgentAvailabilityRead]
    count: int
