"""API error envelope schemas."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class APIErrorCode(StrEnum):
    WORKFLOW_NOT_FOUND = "WORKFLOW_NOT_FOUND"
    INVALID_WORKFLOW_STATE = "INVALID_WORKFLOW_STATE"
    AGENT_EXECUTOR_NOT_REGISTERED = "AGENT_EXECUTOR_NOT_REGISTERED"
    STEP_EXECUTION_FAILED = "STEP_EXECUTION_FAILED"
    CIRCUIT_BREAKER_OPEN = "CIRCUIT_BREAKER_OPEN"
    INVALID_REQUEST = "INVALID_REQUEST"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class APIError(BaseModel):
    """One error's code, human-readable message, and optional structured details."""

    code: APIErrorCode
    message: str
    details: Any | None = None


class APIErrorEnvelope(BaseModel):
    """The `{"error": {...}}` response body returned for all handled API errors."""

    error: APIError
