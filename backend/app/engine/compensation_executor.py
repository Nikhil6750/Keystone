"""Compensation executor contract: the interface every compensation handler satisfies."""

from typing import Any, Protocol

from app.engine.compensation_context import CompensationRequest


class CompensationExecutor(Protocol):
    """One registered compensation handler, resolved by name from a step's handler field."""

    def compensate(self, request: CompensationRequest) -> dict[str, Any]:
        """Reverse the effects of one successful step and return a JSON-compatible result."""
        ...
