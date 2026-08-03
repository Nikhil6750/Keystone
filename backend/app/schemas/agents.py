"""Schemas for the agent-availability and connection-verification APIs."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.adapters.connection import AuthenticationStatus, ConnectionStatus, InstallationStatus


class AgentAvailabilityRead(BaseModel):
    """Serialized availability + connection report for one canonical agent type."""

    model_config = ConfigDict(from_attributes=True)

    agent_type: str
    display_name: str
    enabled: bool
    available: bool
    registered: bool
    execution_mode: str
    reason: str
    installation_status: InstallationStatus
    authentication_status: AuthenticationStatus
    connection_status: ConnectionStatus
    version: str | None
    last_checked_at: str | None
    capabilities: list[str]


class AgentAvailabilityListResponse(BaseModel):
    """Response envelope for `GET /api/v1/agents`."""

    model_config = ConfigDict(from_attributes=True)

    items: list[AgentAvailabilityRead]
    count: int


class AgentConnectionVerifyRead(BaseModel):
    """Response for `POST /api/v1/agents/{agent_type}/verify`.

    Never includes a raw provider response, a credential, an email address,
    or any other account-identifying detail — only this sanitized state.
    """

    model_config = ConfigDict(from_attributes=True)

    agent_type: str
    display_name: str
    enabled: bool
    installation_status: InstallationStatus
    authentication_status: AuthenticationStatus
    connection_status: ConnectionStatus
    registered: bool
    execution_mode: str
    version: str | None
    last_checked_at: datetime | None
    reason: str
