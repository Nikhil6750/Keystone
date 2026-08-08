"""The pluggable interface the scheduler uses to actually run one step.

Kept independent of both the live synchronous `AgentExecutor`
(`app.engine.executor`) and the async `AgentAdapter` contract
(`app.contracts.adapter`) so the scheduler has no hard dependency on either —
a later stage can supply an adapter implementing this protocol against
whichever executor contract it needs, without changing this package. Bridging
`StepRunner` to `AgentAdapter` is future integration work and is not built as
part of this contract — see `docs/contracts.md`'s "Execution interface
architecture" section for the target direction and the identity/result-shape
gaps a real bridge will need to resolve (`StepRunner` carries no
`execution_id`/`agent_id`, and returns a bare `dict[str, Any]` rather than
`AgentAdapter`'s richer `AgentExecutionResult`).

**Cancellation and timeout ownership (read before implementing `StepRunner`):**

- `GraphScheduler` owns both cancellation and the timeout at this layer, not
  the runner. The scheduler races `run()`'s task against its own cancellation
  signal and a wall-clock timeout, and calls `asyncio.Task.cancel()` on the
  runner's coroutine when either fires — the runner receives *no* separate
  cancellation token or callback.
- Consequently, a `StepRunner` implementation **must be cooperatively
  cancellable**: it must reach real `await` points (an `await`ed I/O call, an
  `await asyncio.sleep(0)`, etc.) often enough that `asyncio.CancelledError`
  raised into it at one of those points actually takes effect promptly. A
  runner that performs long blocking (non-awaiting) work directly on the
  event loop — a synchronous subprocess call, a blocking library call, heavy
  synchronous CPU work — will not respond to cancellation or the timeout
  until it eventually reaches an `await`, if ever. Blocking provider/process
  work belongs behind an appropriate async boundary (e.g. `asyncio.to_thread`,
  an async subprocess API, or an async HTTP client) — never called directly.
- `timeout_seconds` is passed through as a hint for runners that manage their
  own timeout (e.g. a subprocess `timeout=` argument) purely so they can fail
  faster/cleaner on their own terms; it is never the runner's responsibility
  to enforce it — the scheduler enforces it independently regardless of what
  the runner does with it.
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
