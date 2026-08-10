"""Stage 8C.3A Dynamic Agent Connection Foundation Models.

Establishes provider-neutral, extensible connection and agent domain entities.
Separates integration connections (`AgentConnection`) from agent identities
(`ConnectedAgent`), supporting 1:N agent-to-connection mappings, custom company
runtimes, and open string identifiers (`agent_id`, `provider_or_runtime`).

Strict secret boundary enforced: zero credential/key fields permitted in
models or requests.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.contracts.enums import AgentCapability

FORBIDDEN_SECRET_SUBSTRINGS = (
    "api_key",
    "apikey",
    "token",
    "password",
    "bearer",
    "secret",
    "authorization",
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class ConnectionKind(StrEnum):
    """Broad category of an integration connection.

    Extensible categories. `provider_or_runtime` remains an unbounded string.
    """

    INSTALLED_RUNTIME = "installed_runtime"
    API = "api"
    LOCAL = "local"
    CUSTOM = "custom"


class AgentConnectionStatus(StrEnum):
    """Status of an integration connection."""

    CONNECTED = "connected"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"
    UNKNOWN = "unknown"


class AgentConnection(BaseModel):
    """Domain model representing an integration connection."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    connection_id: str
    display_name: str
    connection_kind: ConnectionKind | str = ConnectionKind.CUSTOM
    provider_or_runtime: str
    status: AgentConnectionStatus = AgentConnectionStatus.CONNECTED
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("connection_id", "display_name", "provider_or_runtime")
    @classmethod
    def _must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value.strip()

    @field_validator("metadata")
    @classmethod
    def _metadata_must_not_contain_secrets(cls, meta: dict[str, Any]) -> dict[str, Any]:
        for key in meta:
            key_lower = key.lower()
            if any(sub in key_lower for sub in FORBIDDEN_SECRET_SUBSTRINGS):
                raise ValueError(
                    f"metadata key '{key}' is secret-bearing and strictly forbidden"
                )
        return meta


class AgentConnectionCreate(BaseModel):
    """Public creation payload for an `AgentConnection`.

    Strict `extra="forbid"` prevents clients from submitting `api_key` or other
    credentials.
    """

    model_config = ConfigDict(extra="forbid")

    connection_id: str
    display_name: str
    connection_kind: ConnectionKind | str = ConnectionKind.CUSTOM
    provider_or_runtime: str
    status: AgentConnectionStatus = AgentConnectionStatus.CONNECTED
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("connection_id", "display_name", "provider_or_runtime")
    @classmethod
    def _must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value.strip()

    @field_validator("metadata")
    @classmethod
    def _metadata_must_not_contain_secrets(cls, meta: dict[str, Any]) -> dict[str, Any]:
        for key in meta:
            key_lower = key.lower()
            if any(sub in key_lower for sub in FORBIDDEN_SECRET_SUBSTRINGS):
                raise ValueError(
                    f"metadata key '{key}' is secret-bearing and strictly forbidden"
                )
        return meta


class ConnectedAgent(BaseModel):
    """Domain model representing an agent identity backed by a connection."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    agent_id: str
    display_name: str
    connection_id: str
    model_id: str | None = None
    capabilities: list[AgentCapability] = Field(default_factory=list)
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("agent_id", "display_name", "connection_id")
    @classmethod
    def _must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value.strip()

    @field_validator("model_id")
    @classmethod
    def _model_id_not_blank_if_given(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("model_id must not be blank if provided")
        return value.strip() if value is not None else None

    @field_validator("metadata")
    @classmethod
    def _metadata_must_not_contain_secrets(cls, meta: dict[str, Any]) -> dict[str, Any]:
        for key in meta:
            key_lower = key.lower()
            if any(sub in key_lower for sub in FORBIDDEN_SECRET_SUBSTRINGS):
                raise ValueError(
                    f"metadata key '{key}' is secret-bearing and strictly forbidden"
                )
        return meta


class ConnectedAgentCreate(BaseModel):
    """Public creation payload for a `ConnectedAgent`."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    display_name: str
    connection_id: str
    model_id: str | None = None
    capabilities: list[AgentCapability] = Field(default_factory=list)
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("agent_id", "display_name", "connection_id")
    @classmethod
    def _must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value.strip()

    @field_validator("model_id")
    @classmethod
    def _model_id_not_blank_if_given(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("model_id must not be blank if provided")
        return value.strip() if value is not None else None

    @field_validator("metadata")
    @classmethod
    def _metadata_must_not_contain_secrets(cls, meta: dict[str, Any]) -> dict[str, Any]:
        for key in meta:
            key_lower = key.lower()
            if any(sub in key_lower for sub in FORBIDDEN_SECRET_SUBSTRINGS):
                raise ValueError(
                    f"metadata key '{key}' is secret-bearing and strictly forbidden"
                )
        return meta


class ConnectedAgentUpdate(BaseModel):
    """Public partial update payload for a `ConnectedAgent`."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    model_id: str | None = None
    capabilities: list[AgentCapability] | None = None
    enabled: bool | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("display_name", "model_id")
    @classmethod
    def _not_blank_if_given(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("field must not be blank if provided")
        return value.strip() if value is not None else None

    @field_validator("metadata")
    @classmethod
    def _metadata_must_not_contain_secrets(
        cls, meta: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if meta is not None:
            for key in meta:
                key_lower = key.lower()
                if any(sub in key_lower for sub in FORBIDDEN_SECRET_SUBSTRINGS):
                    raise ValueError(
                        f"metadata key '{key}' is secret-bearing and strictly forbidden"
                    )
        return meta
