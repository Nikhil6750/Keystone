"""Deterministic demo adapter: no network, no subprocess, clearly self-labeled.

Disabled by default; registers only when explicitly enabled through settings.
Never registered under a real provider's agent type, and never claims to be
Claude Code, Codex, or Gemini.
"""

from datetime import UTC, datetime
from typing import Any

from app.adapters.base import build_agent_result
from app.engine.executor import StepExecutionRequest


class DemoAgentAdapter:
    """A local, deterministic adapter for demonstration and frontend integration only."""

    def execute(self, request: StepExecutionRequest) -> dict[str, Any]:
        content = (
            f"[DEMO] Simulated result for step '{request.step_name}' "
            f"in workflow {request.workflow_id}. This is not a real agent response."
        )
        return build_agent_result(
            agent_type="demo",
            content=content,
            execution_mode="demo",
            extra_metadata={
                "generated_at": datetime.now(UTC).isoformat(),
                "step_id": request.step_id,
            },
        )
