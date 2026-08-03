"""Circuit-breaker status API."""

from fastapi import APIRouter, Depends

from app.api.deps import get_circuit_breaker_registry
from app.resilience.circuit_breaker import CircuitBreakerRegistry
from app.schemas.resilience import CircuitBreakerListResponse

router = APIRouter(prefix="/resilience", tags=["resilience"])


@router.get("/circuit-breakers", response_model=CircuitBreakerListResponse)
def get_circuit_breakers(
    registry: CircuitBreakerRegistry = Depends(get_circuit_breaker_registry),  # noqa: B008
) -> CircuitBreakerListResponse:
    """Return a safe snapshot of every circuit breaker created so far."""
    snapshots = registry.snapshots()
    return CircuitBreakerListResponse.model_validate({"items": snapshots, "count": len(snapshots)})
