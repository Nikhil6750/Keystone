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

`run()` maintains an explicit in-memory `GraphWorkflowStatus` and, per step,
`GraphStepStatus`, and every real change to either is validated through
`app.engine.workflow.state_machine`'s `transition_graph_workflow`/
`transition_graph_step` — not just constructed ad hoc. All of this bookkeeping
happens exclusively in `run()`'s own single coroutine (never inside `_run_one`,
which executes concurrently as a separate task), so introducing it adds no new
race surface: `_run_one` remains a pure function of its own local state plus
the shared semaphores.

Retries are out of scope here (`GraphStepStatus.RETRYING` exists in the
status vocabulary but this scheduler runs each step at most once) — Stage 3
adds retry behavior as a `StepRunner` decorator, without scheduler changes.

Two distinct kinds of "unordered" exist in this module, deliberately handled
differently:

- The failure-triggered skip cascade (one step fails, some set of transitive
  dependents become `SKIPPED`) stems from a single synchronous event and is
  made deterministic: dependents are processed in workflow declaration order,
  so the same failure on the same graph always skips steps (and emits their
  events) in the same order.
- Genuinely concurrent task completions (multiple independent steps finishing
  in the same scheduling pass) are *not* artificially ordered — there is no
  "true" order for events that actually happened at the same time, so
  `asyncio.wait`'s `done` set is processed in whatever order Python gives it.
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
from app.engine.workflow.state_machine import transition_graph_step, transition_graph_workflow
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
        cancellation = cancellation or CancellationToken()
        sequence = _SequenceCounter()
        await self._emit(sink, sequence, workflow_id, "workflow.started", None, {})

        workflow_status = transition_graph_workflow(
            GraphWorkflowStatus.PENDING, GraphWorkflowStatus.PLANNING
        )
        await self._emit(sink, sequence, workflow_id, "workflow.planning", None, {})

        # Validation happens during "planning": a malformed graph never
        # reaches RUNNING. Raises CycleDetectedError; propagates uncaught,
        # exactly as before this stage's state-machine wiring.
        graph = WorkflowGraph.from_definition(definition)
        step_statuses: dict[str, GraphStepStatus] = {
            key: GraphStepStatus.PENDING for key in graph.steps
        }
        outcomes: dict[str, StepOutcome] = {}

        if cancellation.is_cancelled:
            workflow_status = transition_graph_workflow(
                workflow_status, GraphWorkflowStatus.CANCELLING
            )
            await self._emit(sink, sequence, workflow_id, "workflow.cancelling", None, {})
            for key in graph.steps:
                outcomes[key] = self._cancel_never_started(step_statuses, key)
            workflow_status = transition_graph_workflow(
                workflow_status, GraphWorkflowStatus.CANCELLED
            )
            await self._emit(sink, sequence, workflow_id, "workflow.cancelled", None, {})
            return WorkflowRunResult(status=workflow_status, step_outcomes=outcomes)

        workflow_status = transition_graph_workflow(workflow_status, GraphWorkflowStatus.RUNNING)
        await self._emit(sink, sequence, workflow_id, "workflow.running", None, {})

        workflow_semaphore = asyncio.Semaphore(self._max_concurrent_steps_per_workflow)
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
                step = graph.steps[key]
                step_statuses[key] = transition_graph_step(
                    step_statuses[key], GraphStepStatus.READY
                )
                step_statuses[key] = transition_graph_step(
                    step_statuses[key], GraphStepStatus.RUNNING
                )
                task = asyncio.ensure_future(
                    self._run_one(
                        workflow_semaphore=workflow_semaphore,
                        workflow_id=workflow_id,
                        step=step,
                        # Only this step's *direct* dependencies' outputs —
                        # never the full accumulated workflow history. For
                        # A -> B, A -> C, B,C -> D: D receives B and C's
                        # output, never A's, unless D explicitly depends on A.
                        previous_outputs={
                            dep_key: outcomes[dep_key].output or {} for dep_key in step.depends_on
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
                outcome = self._collect_result(task, key)
                outcomes[key] = outcome
                step_statuses[key] = self._apply_terminal_step_transition(
                    step_statuses[key], outcome.status
                )
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
                    # Deterministic order: declaration order, not set iteration
                    # order — see module docstring for why this differs from
                    # genuinely-concurrent completions below.
                    dependents = sorted(
                        graph.transitive_dependents(key),
                        key=lambda dependent_key: graph.declaration_order[dependent_key],
                    )
                    for dependent_key in dependents:
                        if dependent_key in outcomes or dependent_key in skipped:
                            continue
                        skipped.add(dependent_key)
                        step_statuses[dependent_key] = transition_graph_step(
                            step_statuses[dependent_key], GraphStepStatus.SKIPPED
                        )
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
                outcomes[key] = self._cancel_never_started(step_statuses, key)

        if cancellation.is_cancelled:
            workflow_status = transition_graph_workflow(
                workflow_status, GraphWorkflowStatus.CANCELLING
            )
            await self._emit(sink, sequence, workflow_id, "workflow.cancelling", None, {})
            workflow_status = transition_graph_workflow(
                workflow_status, GraphWorkflowStatus.CANCELLED
            )
        elif any(outcome.status is GraphStepStatus.FAILED for outcome in outcomes.values()):
            workflow_status = transition_graph_workflow(workflow_status, GraphWorkflowStatus.FAILED)
        else:
            workflow_status = transition_graph_workflow(
                workflow_status, GraphWorkflowStatus.SUCCEEDED
            )

        await self._emit(
            sink, sequence, workflow_id, f"workflow.{workflow_status.value}", None, {}
        )
        return WorkflowRunResult(status=workflow_status, step_outcomes=outcomes)

    @staticmethod
    def _apply_terminal_step_transition(
        current: GraphStepStatus, outcome_status: GraphStepStatus
    ) -> GraphStepStatus:
        """Move a `RUNNING` step to its terminal outcome, validated.

        `CANCELLED` always passes through `CANCELLING` first (the required
        `RUNNING -> CANCELLING -> CANCELLED` path) even though `StepOutcome`
        itself only ever records the final `CANCELLED` value — `CANCELLING`
        is transient and has no observable duration in this design, so it is
        validated but not separately surfaced as an outcome.
        """
        if outcome_status is GraphStepStatus.CANCELLED:
            current = transition_graph_step(current, GraphStepStatus.CANCELLING)
            return transition_graph_step(current, GraphStepStatus.CANCELLED)
        return transition_graph_step(current, outcome_status)

    @staticmethod
    def _cancel_never_started(
        step_statuses: dict[str, GraphStepStatus], key: str
    ) -> StepOutcome:
        """A step that never became ready before the run ended: `PENDING -> CANCELLED`
        directly — it never ran, so there is no `CANCELLING` phase to pass through."""
        step_statuses[key] = transition_graph_step(step_statuses[key], GraphStepStatus.CANCELLED)
        now = datetime.now(UTC)
        return StepOutcome(
            key=key,
            status=GraphStepStatus.CANCELLED,
            output=None,
            error_message="workflow cancelled before this step started",
            started_at=now,
            completed_at=now,
        )

    @staticmethod
    def _collect_result(task: "asyncio.Task[StepOutcome]", key: str) -> StepOutcome:
        """Retrieve `_run_one`'s result defensively.

        `_run_one` is designed to never raise — every expected and
        unexpected runner failure is already caught inside it and turned
        into a `FAILED` `StepOutcome`. This is a deliberate backstop, not the
        primary error-handling path: if a future change ever lets something
        escape `_run_one` anyway, one step fails cleanly instead of crashing
        the entire run. Only `Exception` is caught here — `asyncio.CancelledError`,
        `SystemExit`, and `KeyboardInterrupt` are `BaseException`s and are
        never caught or hidden by this handler.
        """
        try:
            return task.result()
        except Exception as exc:  # noqa: BLE001 - defensive backstop, see docstring
            now = datetime.now(UTC)
            return StepOutcome(
                key=key,
                status=GraphStepStatus.FAILED,
                output=None,
                error_message=f"unexpected scheduler error: {exc}",
                started_at=now,
                completed_at=now,
            )

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
            # If both `run_task` and `cancel_wait` become ready in the same
            # event-loop turn (e.g. the step finishes at the exact moment
            # cancellation is requested), `run_task`'s real outcome always
            # wins: `if run_task in done` is checked first below. This is a
            # deliberate, deterministic tie-break — prefer reporting genuine
            # work that actually finished over a same-instant cancellation —
            # not an accident of `asyncio.wait`'s set ordering.
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
        # Awaited inline, not fire-and-forget: transition/event ordering must
        # stay deterministic, and a sink failure must not be silently lost.
        # See `app.engine.workflow.events` for why this is fail-fast by design.
        await sink.on_event(event)


class _SequenceCounter:
    """A simple monotonic counter, local to one `run()` call."""

    def __init__(self) -> None:
        self._value = 0

    def next(self) -> int:
        self._value += 1
        return self._value


__all__ = ["GraphScheduler", "StepOutcome", "WorkflowRunResult"]
