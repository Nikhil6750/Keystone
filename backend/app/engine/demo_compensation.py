"""Deterministic demo compensation handler (`demo.undo`): no network, no subprocess.

Registered only when the demo adapter is enabled (see `main.py`'s lifespan).
Never registered under a real provider's name, and never claims to reverse an
actual external side effect.
"""

from datetime import UTC, datetime
from typing import Any

from app.engine.compensation_context import CompensationRequest

DEMO_COMPENSATION_HANDLER_NAME = "demo.undo"


class DemoCompensationHandler:
    """A local, deterministic, idempotent compensation handler for demonstration only."""

    def compensate(self, request: CompensationRequest) -> dict[str, Any]:
        content = (
            f"[DEMO] Simulated compensation for step '{request.step_name}' "
            f"in workflow {request.workflow_id}. This is not a real reversal of "
            "any external side effect."
        )
        return {
            "handler": DEMO_COMPENSATION_HANDLER_NAME,
            "content": content,
            "metadata": {
                "execution_mode": "demo",
                "compensation": True,
                "generated_at": datetime.now(UTC).isoformat(),
                "step_id": request.step_id,
            },
        }
