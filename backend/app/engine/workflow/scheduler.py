"""Bounded-concurrency, dependency-aware workflow scheduler.

Each `GraphScheduler.run()` call executes one workflow's DAG to completion:
independent steps run concurrently (bounded), a failed step skips its
transitive dependents rather than aborting unrelated branches, and
cancellation stops scheduling new work immediately while in-flight steps are
cancelled cooperatively. State is entirely local to one `run()` call — two
concurrent `run()` calls (even on the same `GraphScheduler` instance) never
share mutable state beyond the intentionally-shared per-agent-type
concurrency limiter, so one workflow's cancellation or failure can never
affect another.

Retries are out of scope here (`GraphStepStatus.RETRYING` exists in the
status vocabulary but this scheduler runs each step at most once) — Stage 3
adds retry behavior as a `StepRunner` decorator, without scheduler changes.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.contracts.workflow import (
    WorkflowDefinition,
    WorkflowExecutionEvent,
    WorkflowStepDefinition,
)
from app.engine.workflow.cancellation import CancellationToken
from app.engine.workflow.events import StateSink
from app.engine.workflow.exceptions import StepRunnerError
from app.engine.workflow.graph import WorkflowGraph
from app.engine.workflow.runner import StepRunner
from app.engine.workflow.status import GraphStepStatus, GraphWorkflowStatus


@dataclass(frozen=True)
class StepOutcome:
    """The terminal result of one step within one scheduler run."""

    key: str
    status: GraphStepStatus
    output: dict[str, Any] | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime


@dataclass(frozen=True)
class WorkflowRunResult:
    """The terminal result of one `GraphScheduler.run()` call."""

    status: GraphWorkflowStatus
    step_outcomes: dict[str, StepOutcome] = field(default_factory=dict)


class GraphScheduler:
    """Runs a `WorkflowDefinition`'s DAG with bounded, isolated concurrency."""

    def __init__(
        self,
        runner: StepRunner,
        *,
        max_concurrent_steps_per_workflow: int = 5,
        max_concurrent_per_agent_type: int = 3,
        default_step_timeout_seconds: float = 30.0,
    ) -> None:
        if max_concurrent_steps_per_workflow < 1:
            raise ValueError("max_concurrent_steps_per_workflow must be at least 1")
        if max_concurrent_per_agent_type < 1:
            raise ValueError("max_concurrent_per_agent_type must be at least 1")
        if default_step_timeout_seconds <= 0:
            raise ValueError("default_step_timeout_seconds must be positive")
        self._runner = runner
        self._max_concurrent_steps_per_workflow = max_concurrent_steps_per_workflow
        self._max_concurrent_per_agent_type = max_concurrent_per_agent_type
        self._default_step_timeout_seconds = default_step_timeout_seconds
        # Shared across every `run()` call on this instance, deliberately: it
        # bounds how hard any single agent type is hit regardless of how many
        # workflows are running concurrently through this scheduler.
        self._agent_semaphores: dict[str, asyncio.Semaphore] = {}

    def _agent_semaphore(self, agent_type: str) -> asyncio.Semaphore:
        semaphore = self._agent_semaphores.get(agent_type)
        if semaphore is None:
            semaphore = asyncio.Semaphore(self._max_concurrent_per_agent_type)
            self._agent_semaphores[agent_type] = semaphore
        return semaphore

    async def run(
        self,
        definition: WorkflowDefinition,
        *,
        workflow_id: str,
        cancellation: CancellationToken | None = None,
        sink: StateSink | None = None,
    ) -> WorkflowRunResult:
        graph = WorkflowGraph.from_definition(definition)
        cancellation = cancellation or CancellationToken()
        workflow_semaphore = asyncio.Semaphore(self._max_concurrent_steps_per_workflow)

        sequence = _SequenceCounter()
        await self._emit(sink, sequence, workflow_id, "workflow.started", None, {})

        outcomes: dict[str, StepOutcome] = {}
        completed_success: set[str] = set()
        scheduled: set[str] = set()
        skipped: set[str] = set()
        pending_tasks: dict[asyncio.Task[StepOutcome], str] = {}

        def launch_ready() -> None:
            if cancellation.is_cancelled:
                return
            ready = graph.ready_steps(completed_success, exclude=scheduled | skipped)
            for key in ready:
                scheduled.add(key)
                task = asyncio.ensure_future(
                    self._run_one(
                        workflow_semaphore=workflow_semaphore,
                        workflow_id=workflow_id,
                        step=graph.steps[key],
                        previous_outputs={
                            dep_key: outcomes[dep_key].output or {}
                            for dep_key in completed_success
                        },
                        cancellation=cancellation,
                    )
                )
                pending_tasks[task] = key

        launch_ready()

        while pending_tasks:
            done, _ = await asyncio.wait(pending_tasks.keys(), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                key = pending_tasks.pop(task)
                outcome = task.result()
                outcomes[key] = outcome
                await self._emit(
                    sink,
                    sequence,
                    workflow_id,
                    f"step.{outcome.status.value}",
                    key,
                    {"error_message": outcome.error_message} if outcome.error_message else {},
                )
                if outcome.status is GraphStepStatus.SUCCEEDED:
                    completed_success.add(key)
                elif outcome.status is GraphStepStatus.FAILED:
                    for dependent_key in graph.transitive_dependents(key):
                        if dependent_key in outcomes or dependent_key in skipped:
                            continue
                        skipped.add(dependent_key)
                        now = datetime.now(UTC)
                        outcomes[dependent_key] = StepOutcome(
                            key=dependent_key,
                            status=GraphStepStatus.SKIPPED,
                            output=None,
                            error_message=f"upstream step '{key}' failed",
                            started_at=now,
                            completed_at=now,
                        )
                        await self._emit(
                            sink,
                            sequence,
                            workflow_id,
                            "step.skipped",
                            dependent_key,
                            {"reason": f"upstream step '{key}' failed"},
                        )
            launch_ready()

        # Steps never reached at all (cancelled before they ever became ready).
        for key in graph.steps:
            if key not in outcomes:
                now = datetime.now(UTC)
                outcomes[key] = StepOutcome(
                    key=key,
                    status=GraphStepStatus.CANCELLED,
                    output=None,
                    error_message="workflow cancelled before this step started",
                    started_at=now,
                    completed_at=now,
                )

        if cancellation.is_cancelled:
            overall = GraphWorkflowStatus.CANCELLED
        elif any(outcome.status is GraphStepStatus.FAILED for outcome in outcomes.values()):
            overall = GraphWorkflowStatus.FAILED
        else:
            overall = GraphWorkflowStatus.SUCCEEDED

        await self._emit(sink, sequence, workflow_id, f"workflow.{overall.value}", None, {})
        return WorkflowRunResult(status=overall, step_outcomes=outcomes)

    async def _run_one(
        self,
        *,
        workflow_semaphore: asyncio.Semaphore,
        workflow_id: str,
        step: WorkflowStepDefinition,
        previous_outputs: dict[str, dict[str, Any]],
        cancellation: CancellationToken,
    ) -> StepOutcome:
        started_at = datetime.now(UTC)
        async with workflow_semaphore, self._agent_semaphore(step.agent_type):
            if cancellation.is_cancelled:
                return StepOutcome(
                    key=step.key,
                    status=GraphStepStatus.CANCELLED,
                    output=None,
                    error_message="workflow cancelled before step started",
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                )

            timeout = step.timeout_seconds or self._default_step_timeout_seconds
            run_task: asyncio.Task[dict[str, Any]] = asyncio.ensure_future(
                self._runner.run(
                    workflow_id=workflow_id,
                    step=step,
                    previous_outputs=previous_outputs,
                    timeout_seconds=timeout,
                )
            )
            cancel_wait: asyncio.Task[None] = asyncio.ensure_future(cancellation.wait())
            done, _pending = await asyncio.wait(
                {run_task, cancel_wait}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )

            if run_task in done:
                cancel_wait.cancel()
                try:
                    output = run_task.result()
                except StepRunnerError as exc:
                    return StepOutcome(
                        key=step.key,
                        status=GraphStepStatus.FAILED,
                        output=None,
                        error_message=str(exc),
                        started_at=started_at,
                        completed_at=datetime.now(UTC),
                    )
                except Exception as exc:  # noqa: BLE001 - any runner failure fails only this step
                    return StepOutcome(
                        key=step.key,
                        status=GraphStepStatus.FAILED,
                        output=None,
                        error_message=f"unexpected error: {exc}",
                        started_at=started_at,
                        completed_at=datetime.now(UTC),
                    )
                return StepOutcome(
                    key=step.key,
                    status=GraphStepStatus.SUCCEEDED,
                    output=output,
                    error_message=None,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                )

            if cancel_wait in done:
                run_task.cancel()
                return StepOutcome(
                    key=step.key,
                    status=GraphStepStatus.CANCELLED,
                    output=None,
                    error_message="workflow cancelled",
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                )

            # Neither finished within `timeout`.
            run_task.cancel()
            cancel_wait.cancel()
            return StepOutcome(
                key=step.key,
                status=GraphStepStatus.FAILED,
                output=None,
                error_message=f"step timed out after {timeout}s",
                started_at=started_at,
                completed_at=datetime.now(UTC),
            )

    @staticmethod
    async def _emit(
        sink: StateSink | None,
        sequence: "_SequenceCounter",
        workflow_id: str,
        event_type: str,
        step_id: str | None,
        payload: dict[str, Any],
    ) -> None:
        if sink is None:
            return
        event = WorkflowExecutionEvent(
            event_id=uuid.uuid4().hex,
            workflow_id=workflow_id,
            step_id=step_id,
            event_type=event_type,
            sequence_number=sequence.next(),
            timestamp=datetime.now(UTC),
            payload=payload,
        )
        await sink.on_event(event)


class _SequenceCounter:
    """A simple monotonic counter, local to one `run()` call."""

    def __init__(self) -> None:
        self._value = 0

    def next(self) -> int:
        self._value += 1
        return self._value


__all__ = ["GraphScheduler", "StepOutcome", "WorkflowRunResult"]
