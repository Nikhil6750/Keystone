"""Deterministic, controllable async `StepRunner`/`StateSink` fakes for
graph scheduler tests."""

import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.contracts.workflow import WorkflowExecutionEvent, WorkflowStepDefinition
from app.engine.workflow.exceptions import StepRunnerError


@dataclass
class FakeStepRunner:
    """A controllable `StepRunner`.

    - `outputs`: per-key output payload (default `{}` if not set).
    - `failures`: keys that raise `StepRunnerError` instead of succeeding.
    - `crashes`: keys that raise a plain, unexpected `RuntimeError` instead of
      `StepRunnerError` — simulates a runner bug, not a normal step failure.
    - `delays`: per-key `asyncio.sleep` duration before returning/raising.
    - `release_events`: if a key has an entry, the runner awaits it before
      proceeding, letting a test control exactly when a step "finishes".
    - `previous_outputs_seen`: records the exact `previous_outputs` dict each
      call received, keyed by step key, for dependency-scoping assertions.
    - `max_concurrent_observed` records the highest number of overlapping
      `run()` calls seen at once, for bounded-concurrency assertions.
    """

    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    failures: set[str] = field(default_factory=set)
    crashes: set[str] = field(default_factory=set)
    delays: dict[str, float] = field(default_factory=dict)
    release_events: dict[str, asyncio.Event] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    previous_outputs_seen: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    concurrent_now: int = 0
    max_concurrent_observed: int = 0

    async def run(
        self,
        *,
        workflow_id: str,
        step: WorkflowStepDefinition,
        previous_outputs: dict[str, dict[str, Any]],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        self.calls.append(step.key)
        self.previous_outputs_seen[step.key] = dict(previous_outputs)
        self.concurrent_now += 1
        self.max_concurrent_observed = max(self.max_concurrent_observed, self.concurrent_now)
        try:
            if step.key in self.release_events:
                await self.release_events[step.key].wait()
            elif step.key in self.delays:
                await asyncio.sleep(self.delays[step.key])
            if step.key in self.crashes:
                raise RuntimeError("boom")
            if step.key in self.failures:
                raise StepRunnerError(f"simulated failure for '{step.key}'")
            return dict(self.outputs.get(step.key, {}))
        finally:
            self.concurrent_now -= 1


@dataclass
class RecordingStateSink:
    """Collects every emitted `WorkflowExecutionEvent`, in emission order."""

    events: list[WorkflowExecutionEvent] = field(default_factory=list)

    async def on_event(self, event: WorkflowExecutionEvent) -> None:
        self.events.append(event)
