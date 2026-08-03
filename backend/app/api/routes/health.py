"""Health check route."""

from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Report service liveness and version information."""
    settings = get_settings()
    return HealthResponse(
        status="healthy",
        service=settings.app_name,
        version=settings.app_version,
    )
