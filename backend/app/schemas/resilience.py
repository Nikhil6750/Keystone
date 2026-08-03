"""Schemas for the circuit-breaker resilience API."""

from pydantic import BaseModel, ConfigDict

from app.resilience.circuit_breaker import CircuitState


class CircuitBreakerRead(BaseModel):
    """Serialized snapshot of one agent type's circuit breaker."""

    model_config = ConfigDict(from_attributes=True)

    agent_type: str
    state: CircuitState
    failure_count: int
    failure_threshold: int
    recovery_timeout_seconds: float
    retry_after_seconds: float
    half_open_probe_in_flight: bool


class CircuitBreakerListResponse(BaseModel):
    """Response envelope for `GET /api/v1/resilience/circuit-breakers`."""

    model_config = ConfigDict(from_attributes=True)

    items: list[CircuitBreakerRead]
    count: int
