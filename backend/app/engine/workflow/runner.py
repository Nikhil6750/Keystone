"""The pluggable interface the scheduler uses to actually run one step.

Kept independent of both the live synchronous `AgentExecutor`
(`app.engine.executor`) and the async `AgentAdapter` contract
(`app.contracts.adapter`) so the scheduler has no hard dependency on either —
a later stage can supply an adapter implementing this protocol against
whichever executor contract it needs, without changing this package.
"""

from typing import Any, Protocol

from app.contracts.workflow import WorkflowStepDefinition


class StepRunner(Protocol):
    """Runs one workflow step and returns its JSON-compatible output."""

    async def run(
        self,
        *,
        workflow_id: str,
        step: WorkflowStepDefinition,
        previous_outputs: dict[str, dict[str, Any]],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        """Execute `step`. Raise `StepRunnerError` for an expected failure.

        `timeout_seconds` is informational for runners that manage their own
        timeout (e.g. a subprocess `timeout=` argument); the scheduler also
        enforces this timeout independently and will cancel a runner that
        does not return in time.
        """
        ...


__all__ = ["StepRunner"]
