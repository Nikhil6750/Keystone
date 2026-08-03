"""Schemas for the audit-event, chain-verification, and provenance APIs."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.audit.types import ActorType, AuditEventType


class AuditEventRead(BaseModel):
    """Serialized representation of one audit event.

    Reused for both `GET .../audit-events` and `GET .../provenance` — the two
    endpoints return the same event shape, differing only in whether chain
    validity accompanies the list.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_id: str
    step_id: str | None
    execution_attempt_id: str | None
    compensation_attempt_id: str | None
    sequence_number: int
    event_type: AuditEventType
    actor_type: ActorType
    actor_id: str
    payload: dict[str, Any]
    previous_hash: str
    event_hash: str
    created_at: datetime


class AuditEventListResponse(BaseModel):
    """Response envelope for `GET /api/v1/workflows/{workflow_id}/audit-events`."""

    model_config = ConfigDict(from_attributes=True)

    items: list[AuditEventRead]
    count: int


class ChainVerificationRead(BaseModel):
    """Response for `GET /api/v1/workflows/{workflow_id}/audit-chain/verify`."""

    model_config = ConfigDict(from_attributes=True)

    workflow_id: str
    valid: bool
    event_count: int
    first_invalid_sequence: int | None
    reason: str | None


class ProvenanceRead(BaseModel):
    """Response for `GET /api/v1/workflows/{workflow_id}/provenance`."""

    model_config = ConfigDict(from_attributes=True)

    workflow_id: str
    chain_valid: bool
    events: list[AuditEventRead]
