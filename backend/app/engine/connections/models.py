"""Stage 8C.3A Dynamic Agent Connection Foundation Models.

Establishes provider-neutral, extensible connection and agent domain entities.
Separates integration connections (`AgentConnection`) from agent identities
(`ConnectedAgent`), supporting 1:N agent-to-connection mappings, custom company
runtimes, and open string identifiers (`agent_id`, `provider_or_runtime`).

Strict secret boundary enforced: zero credential/key fields permitted in
models or requests. Frozen domain models prevent direct field mutation.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.contracts.enums import AgentCapability

MAX_ID_LENGTH = 64
MAX_NAME_LENGTH = 128
MAX_METADATA_ITEMS = 32
MAX_METADATA_KEY_LENGTH = 64
MAX_METADATA_VALUE_LENGTH = 512

RESERVED_METADATA_KEYS = frozenset(
    {"connection_id", "provider_or_runtime", "model_id", "connection_kind"}
)

FORBIDDEN_SECRET_TOKENS = frozenset(
    {
        "apikey",
        "api_key",
        "accesstoken",
        "access_token",
        "token",
        "bearer",
        "bearertoken",
        "authorization",
        "auth",
        "password",
        "passwd",
        "secret",
        "clientsecret",
        "client_secret",
        "privatekey",
        "private_key",
    }
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def validate_metadata(meta: dict[str, Any] | None) -> dict[str, str]:
    """Validates and sanitizes metadata dicts.

    Metadata must be a safe, shallow string-to-string dictionary with strict
    bounds, no nested structures, no reserved internal keys, and no
    secret-bearing key names (under case and punctuation normalization).
    """
    if meta is None:
        return {}

    if not isinstance(meta, dict):
        raise ValueError("metadata must be a dictionary")

    if len(meta) > MAX_METADATA_ITEMS:
        raise ValueError(
            f"metadata exceeds maximum allowed entries ({len(meta)} > {MAX_METADATA_ITEMS})"
        )

    validated: dict[str, str] = {}
    for key, val in meta.items():
        if not isinstance(key, str) or not isinstance(val, str):
            raise ValueError(
                f"metadata entry '{key}' must have string key and string value "
                "(no nested objects or lists)"
            )

        key_clean = key.strip()
        if not key_clean:
            raise ValueError("metadata key must not be blank")

        if len(key_clean) > MAX_METADATA_KEY_LENGTH:
            raise ValueError(
                f"metadata key '{key_clean}' exceeds maximum length ({MAX_METADATA_KEY_LENGTH})"
            )

        if len(val) > MAX_METADATA_VALUE_LENGTH:
            raise ValueError(
                f"metadata value for '{key_clean}' exceeds maximum length "
                f"({MAX_METADATA_VALUE_LENGTH})"
            )

        key_lower = key_clean.lower()
        if key_lower in RESERVED_METADATA_KEYS:
            raise ValueError(
                f"metadata key '{key_clean}' is a reserved internal bridge key"
            )

        normalized_key = (
            key_lower.replace("-", "").replace("_", "").replace(" ", "").replace(":", "")
        )
        if normalized_key in FORBIDDEN_SECRET_TOKENS or any(
            t in normalized_key
            for t in (
                "apikey",
                "accesstoken",
                "bearertoken",
                "authorization",
                "clientsecret",
                "privatekey",
                "password",
                "passwd",
            )
        ):
            raise ValueError(
                f"metadata key '{key_clean}' is secret-bearing and strictly forbidden"
            )

        validated[key_clean] = val

    return validated


class ConnectionKind(StrEnum):
    """Broad category of an integration connection.

    Closed set of integration mechanism categories. `provider_or_runtime`
    remains an unbounded open string for specific execution engines.
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
    """Domain model representing an integration connection. Frozen for safety."""

    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    connection_id: str
    display_name: str
    connection_kind: ConnectionKind = ConnectionKind.CUSTOM
    provider_or_runtime: str
    status: AgentConnectionStatus = AgentConnectionStatus.CONNECTED
    metadata: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("connection_id", "display_name", "provider_or_runtime")
    @classmethod
    def _must_not_be_blank_and_bounded(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("value must not be blank")
        if len(clean) > MAX_NAME_LENGTH:
            raise ValueError(f"field exceeds maximum length ({MAX_NAME_LENGTH})")
        return clean

    @field_validator("connection_id")
    @classmethod
    def _connection_id_bounded(cls, value: str) -> str:
        clean = value.strip()
        if len(clean) > MAX_ID_LENGTH:
            raise ValueError(f"connection_id exceeds maximum length ({MAX_ID_LENGTH})")
        return clean

    @field_validator("metadata")
    @classmethod
    def _validate_metadata_field(cls, meta: dict[str, Any]) -> dict[str, str]:
        return validate_metadata(meta)


class AgentConnectionCreate(BaseModel):
    """Public creation payload for an `AgentConnection`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    connection_id: str
    display_name: str
    connection_kind: ConnectionKind = ConnectionKind.CUSTOM
    provider_or_runtime: str
    status: AgentConnectionStatus = AgentConnectionStatus.CONNECTED
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("connection_id", "display_name", "provider_or_runtime")
    @classmethod
    def _must_not_be_blank_and_bounded(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("value must not be blank")
        if len(clean) > MAX_NAME_LENGTH:
            raise ValueError(f"field exceeds maximum length ({MAX_NAME_LENGTH})")
        return clean

    @field_validator("connection_id")
    @classmethod
    def _connection_id_bounded(cls, value: str) -> str:
        clean = value.strip()
        if len(clean) > MAX_ID_LENGTH:
            raise ValueError(f"connection_id exceeds maximum length ({MAX_ID_LENGTH})")
        return clean

    @field_validator("metadata")
    @classmethod
    def _validate_metadata_field(cls, meta: dict[str, Any]) -> dict[str, str]:
        return validate_metadata(meta)


class AgentConnectionUpdate(BaseModel):
    """Public partial update payload for an `AgentConnection`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    display_name: str | None = None
    status: AgentConnectionStatus | None = None
    metadata: dict[str, str] | None = None

    @field_validator("display_name")
    @classmethod
    def _not_blank_if_given(cls, value: str | None) -> str | None:
        if value is not None:
            clean = value.strip()
            if not clean:
                raise ValueError("display_name must not be blank if provided")
            if len(clean) > MAX_NAME_LENGTH:
                raise ValueError(f"display_name exceeds maximum length ({MAX_NAME_LENGTH})")
            return clean
        return None

    @field_validator("metadata")
    @classmethod
    def _validate_metadata_field(
        cls, meta: dict[str, Any] | None
    ) -> dict[str, str] | None:
        if meta is not None:
            return validate_metadata(meta)
        return None


class ConnectedAgent(BaseModel):
    """Domain model representing an agent identity backed by a connection. Frozen."""

    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    agent_id: str
    display_name: str
    connection_id: str
    model_id: str | None = None
    capabilities: list[AgentCapability] = Field(default_factory=list)
    enabled: bool = True
    metadata: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("agent_id", "display_name", "connection_id")
    @classmethod
    def _must_not_be_blank_and_bounded(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("value must not be blank")
        if len(clean) > MAX_NAME_LENGTH:
            raise ValueError(f"field exceeds maximum length ({MAX_NAME_LENGTH})")
        return clean

    @field_validator("agent_id", "connection_id")
    @classmethod
    def _ids_bounded(cls, value: str) -> str:
        clean = value.strip()
        if len(clean) > MAX_ID_LENGTH:
            raise ValueError(f"ID exceeds maximum length ({MAX_ID_LENGTH})")
        return clean

    @field_validator("model_id")
    @classmethod
    def _model_id_not_blank_if_given(cls, value: str | None) -> str | None:
        if value is not None:
            clean = value.strip()
            if not clean:
                raise ValueError("model_id must not be blank if provided")
            if len(clean) > MAX_NAME_LENGTH:
                raise ValueError(f"model_id exceeds maximum length ({MAX_NAME_LENGTH})")
            return clean
        return None

    @field_validator("metadata")
    @classmethod
    def _validate_metadata_field(cls, meta: dict[str, Any]) -> dict[str, str]:
        return validate_metadata(meta)


class ConnectedAgentCreate(BaseModel):
    """Public creation payload for a `ConnectedAgent`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_id: str
    display_name: str
    connection_id: str
    model_id: str | None = None
    capabilities: list[AgentCapability] = Field(default_factory=list)
    enabled: bool = True
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("agent_id", "display_name", "connection_id")
    @classmethod
    def _must_not_be_blank_and_bounded(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("value must not be blank")
        if len(clean) > MAX_NAME_LENGTH:
            raise ValueError(f"field exceeds maximum length ({MAX_NAME_LENGTH})")
        return clean

    @field_validator("agent_id", "connection_id")
    @classmethod
    def _ids_bounded(cls, value: str) -> str:
        clean = value.strip()
        if len(clean) > MAX_ID_LENGTH:
            raise ValueError(f"ID exceeds maximum length ({MAX_ID_LENGTH})")
        return clean

    @field_validator("model_id")
    @classmethod
    def _model_id_not_blank_if_given(cls, value: str | None) -> str | None:
        if value is not None:
            clean = value.strip()
            if not clean:
                raise ValueError("model_id must not be blank if provided")
            if len(clean) > MAX_NAME_LENGTH:
                raise ValueError(f"model_id exceeds maximum length ({MAX_NAME_LENGTH})")
            return clean
        return None

    @field_validator("metadata")
    @classmethod
    def _validate_metadata_field(cls, meta: dict[str, Any]) -> dict[str, str]:
        return validate_metadata(meta)


class ConnectedAgentUpdate(BaseModel):
    """Public partial update payload for a `ConnectedAgent`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    display_name: str | None = None
    model_id: str | None = None
    capabilities: list[AgentCapability] | None = None
    enabled: bool | None = None
    metadata: dict[str, str] | None = None

    @field_validator("display_name", "model_id")
    @classmethod
    def _not_blank_if_given(cls, value: str | None) -> str | None:
        if value is not None:
            clean = value.strip()
            if not clean:
                raise ValueError("field must not be blank if provided")
            if len(clean) > MAX_NAME_LENGTH:
                raise ValueError(f"field exceeds maximum length ({MAX_NAME_LENGTH})")
            return clean
        return None

    @field_validator("metadata")
    @classmethod
    def _validate_metadata_field(
        cls, meta: dict[str, Any] | None
    ) -> dict[str, str] | None:
        if meta is not None:
            return validate_metadata(meta)
        return None
