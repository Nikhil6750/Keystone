"""Tests for `GraphScheduler` against the Stage 2 acceptance scenarios."""

import asyncio
from typing import Any

import pytest

from app.contracts.workflow import WorkflowDefinition
from app.engine.workflow.cancellation import CancellationToken
from app.engine.workflow.scheduler import GraphScheduler
from app.engine.workflow.status import GraphStepStatus, GraphWorkflowStatus
from tests.support.graph_fakes import FakeStepRunner, RecordingStateSink


def _step(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"key": "a", "name": "step-a", "agent_type": "demo"}
    base.update(overrides)
    return base


def _definition(steps: list[dict[str, Any]], **overrides: Any) -> WorkflowDefinition:
    base: dict[str, Any] = {"name": "wf", "steps": steps}
    base.update(overrides)
    return WorkflowDefinition.model_validate(base)


# 1. Linear graph: A -> B -> C
async def test_linear_graph_runs_in_dependency_order() -> None:
    runner = FakeStepRunner()
    scheduler = GraphScheduler(runner)
    definition = _definition(
        [_step(key="a"), _step(key="b", depends_on=["a"]), _step(key="c", depends_on=["b"])]
    )
    result = await scheduler.run(definition, workflow_id="wf-1")
    assert result.status is GraphWorkflowStatus.SUCCEEDED
    assert runner.calls == ["a", "b", "c"]


# 2. Fan-out: A -> B, C, D
async def test_fan_out_runs_dependents_concurrently() -> None:
    release_b = asyncio.Event()
    release_c = asyncio.Event()
    release_d = asyncio.Event()
    runner = FakeStepRunner(release_events={"b": release_b, "c": release_c, "d": release_d})
    scheduler = GraphScheduler(runner, max_concurrent_steps_per_workflow=3)
    definition = _definition(
        [
            _step(key="a"),
            _step(key="b", depends_on=["a"]),
            _step(key="c", depends_on=["a"]),
            _step(key="d", depends_on=["a"]),
        ]
    )

    run_task = asyncio.ensure_future(scheduler.run(definition, workflow_id="wf-2"))
    for _ in range(50):
        if runner.concurrent_now == 3:
            break
        await asyncio.sleep(0.01)
    assert runner.concurrent_now == 3, "b, c, d should be running concurrently"
    release_b.set()
    release_c.set()
    release_d.set()
    result = await run_task
    assert result.status is GraphWorkflowStatus.SUCCEEDED
    assert runner.max_concurrent_observed == 3


# 3. Fan-in: B, C, D -> E
async def test_fan_in_waits_for_all_dependencies() -> None:
    runner = FakeStepRunner()
    scheduler = GraphScheduler(runner)
    definition = _definition(
        [
            _step(key="b"),
            _step(key="c"),
            _step(key="d"),
            _step(key="e", depends_on=["b", "c", "d"]),
        ]
    )
    result = await scheduler.run(definition, workflow_id="wf-3")
    assert result.status is GraphWorkflowStatus.SUCCEEDED
    assert runner.calls[-1] == "e"
    assert set(runner.calls[:3]) == {"b", "c", "d"}


# 4. Independent parallel steps
async def test_independent_steps_all_run_concurrently_up_to_the_bound() -> None:
    runner = FakeStepRunner(delays={"a": 0.05, "b": 0.05, "c": 0.05})
    scheduler = GraphScheduler(runner, max_concurrent_steps_per_workflow=3)
    definition = _definition([_step(key="a"), _step(key="b"), _step(key="c")])
    result = await scheduler.run(definition, workflow_id="wf-4")
    assert result.status is GraphWorkflowStatus.SUCCEEDED
    assert runner.max_concurrent_observed == 3


# 5. Cycle rejection
async def test_cycle_is_rejected_before_any_step_runs() -> None:
    from app.engine.workflow.exceptions import CycleDetectedError

    runner = FakeStepRunner()
    scheduler = GraphScheduler(runner)
    definition = _definition([_step(key="a", depends_on=["b"]), _step(key="b", depends_on=["a"])])
    with pytest.raises(CycleDetectedError):
        await scheduler.run(definition, workflow_id="wf-5")
    assert runner.calls == []


# 6. Missing dependency rejection (validated at the contract layer)
def test_missing_dependency_is_rejected_at_definition_time() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _definition([_step(key="a", depends_on=["missing"])])


# 7. Step failure blocks dependent steps
async def test_step_failure_skips_transitive_dependents_but_not_independent_branches() -> None:
    runner = FakeStepRunner(failures={"a"})
    scheduler = GraphScheduler(runner)
    definition = _definition(
        [
            _step(key="a"),
            _step(key="b", depends_on=["a"]),
            _step(key="c", depends_on=["b"]),
            _step(key="independent"),
        ]
    )
    result = await scheduler.run(definition, workflow_id="wf-7")
    assert result.status is GraphWorkflowStatus.FAILED
    assert result.step_outcomes["a"].status is GraphStepStatus.FAILED
    assert result.step_outcomes["b"].status is GraphStepStatus.SKIPPED
    assert result.step_outcomes["c"].status is GraphStepStatus.SKIPPED
    assert result.step_outcomes["independent"].status is GraphStepStatus.SUCCEEDED
    assert "independent" in runner.calls
    assert "b" not in runner.calls
    assert "c" not in runner.calls


# 8. Cancellation during parallel execution
async def test_cancellation_stops_scheduling_new_work() -> None:
    release_a = asyncio.Event()
    runner = FakeStepRunner(release_events={"a": release_a})
    scheduler = GraphScheduler(runner)
    cancellation = CancellationToken()
    definition = _definition(
        [
            _step(key="a"),
            _step(key="b", depends_on=["a"]),
            _step(key="never_reached", depends_on=["b"]),
        ]
    )

    run_task = asyncio.ensure_future(
        scheduler.run(definition, workflow_id="wf-8", cancellation=cancellation)
    )
    await asyncio.sleep(0.02)
    cancellation.cancel()
    release_a.set()
    result = await run_task

    assert result.status is GraphWorkflowStatus.CANCELLED
    assert result.step_outcomes["b"].status is GraphStepStatus.CANCELLED
    assert result.step_outcomes["never_reached"].status is GraphStepStatus.CANCELLED
    assert "b" not in runner.calls
    assert "never_reached" not in runner.calls


async def test_in_flight_step_is_cancelled_responsively_not_awaited_to_completion() -> None:
    hang_forever = asyncio.Event()  # never set: the step would hang without cancellation
    runner = FakeStepRunner(release_events={"a": hang_forever})
    scheduler = GraphScheduler(runner)
    cancellation = CancellationToken()
    definition = _definition([_step(key="a")])

    run_task = asyncio.ensure_future(
        scheduler.run(definition, workflow_id="wf-8b", cancellation=cancellation)
    )
    await asyncio.sleep(0.02)
    cancellation.cancel()
    result = await asyncio.wait_for(run_task, timeout=2.0)
    assert result.status is GraphWorkflowStatus.CANCELLED
    assert result.step_outcomes["a"].status is GraphStepStatus.CANCELLED


# 9. Workflow isolation when two workflows run simultaneously
async def test_two_concurrent_workflows_do_not_share_state() -> None:
    runner_1 = FakeStepRunner(outputs={"a": {"workflow": "one"}})
    runner_2 = FakeStepRunner(failures={"a"})
    scheduler_1 = GraphScheduler(runner_1)
    scheduler_2 = GraphScheduler(runner_2)
    definition = _definition([_step(key="a")])

    result_1, result_2 = await asyncio.gather(
        scheduler_1.run(definition, workflow_id="wf-9a"),
        scheduler_2.run(definition, workflow_id="wf-9b"),
    )
    assert result_1.status is GraphWorkflowStatus.SUCCEEDED
    assert result_1.step_outcomes["a"].output == {"workflow": "one"}
    assert result_2.status is GraphWorkflowStatus.FAILED


async def test_cancelling_one_workflow_does_not_affect_a_concurrent_sibling() -> None:
    release_shared = asyncio.Event()
    runner = FakeStepRunner(release_events={"a": release_shared})
    scheduler = GraphScheduler(runner, max_concurrent_per_agent_type=5)
    definition = _definition([_step(key="a")])
    cancelled_token = CancellationToken()

    cancelled_task = asyncio.ensure_future(
        scheduler.run(definition, workflow_id="wf-9c", cancellation=cancelled_token)
    )
    healthy_task = asyncio.ensure_future(
        scheduler.run(_definition([_step(key="a", agent_type="other")]), workflow_id="wf-9d")
    )
    await asyncio.sleep(0.02)
    cancelled_token.cancel()
    release_shared.set()

    cancelled_result, healthy_result = await asyncio.gather(cancelled_task, healthy_task)
    assert cancelled_result.status is GraphWorkflowStatus.CANCELLED
    assert healthy_result.status is GraphWorkflowStatus.SUCCEEDED


# 10. Restart-safe persisted state preparation: every transition flows through StateSink
async def test_every_step_transition_is_emitted_to_the_state_sink() -> None:
    runner = FakeStepRunner()
    scheduler = GraphScheduler(runner)
    sink = RecordingStateSink()
    definition = _definition([_step(key="a"), _step(key="b", depends_on=["a"])])
    await scheduler.run(definition, workflow_id="wf-10", sink=sink)

    event_types = [event.event_type for event in sink.events]
    assert event_types[0] == "workflow.started"
    assert "step.succeeded" in event_types
    assert event_types[-1] == "workflow.succeeded"
    # Sequence numbers are strictly increasing and workflow-scoped.
    sequence_numbers = [event.sequence_number for event in sink.events]
    assert sequence_numbers == sorted(sequence_numbers)
    assert all(event.workflow_id == "wf-10" for event in sink.events)


# Bounded concurrency
async def test_per_agent_type_concurrency_is_bounded_across_a_single_run() -> None:
    runner = FakeStepRunner(delays={"a": 0.05, "b": 0.05, "c": 0.05, "d": 0.05})
    scheduler = GraphScheduler(
        runner, max_concurrent_steps_per_workflow=10, max_concurrent_per_agent_type=2
    )
    definition = _definition(
        [
            _step(key="a", agent_type="shared"),
            _step(key="b", agent_type="shared"),
            _step(key="c", agent_type="shared"),
            _step(key="d", agent_type="shared"),
        ]
    )
    result = await scheduler.run(definition, workflow_id="wf-bound")
    assert result.status is GraphWorkflowStatus.SUCCEEDED
    assert runner.max_concurrent_observed <= 2


# Timeout propagation
async def test_step_exceeding_its_timeout_fails_the_step_not_the_process() -> None:
    never_release = asyncio.Event()
    runner = FakeStepRunner(release_events={"a": never_release})
    scheduler = GraphScheduler(runner)
    definition = _definition([_step(key="a", timeout_seconds=0.05)])
    result = await asyncio.wait_for(
        scheduler.run(definition, workflow_id="wf-timeout"), timeout=2.0
    )
    assert result.status is GraphWorkflowStatus.FAILED
    assert result.step_outcomes["a"].status is GraphStepStatus.FAILED
    assert "timed out" in (result.step_outcomes["a"].error_message or "")


# Determinism
async def test_scheduling_order_is_deterministic_for_the_same_graph() -> None:
    definition = _definition(
        [
            _step(key="a"),
            _step(key="b"),
            _step(key="c", depends_on=["a", "b"]),
        ]
    )
    calls_by_run: list[list[str]] = []
    for _ in range(3):
        runner = FakeStepRunner()
        scheduler = GraphScheduler(runner)
        await scheduler.run(definition, workflow_id="wf-det")
        calls_by_run.append(list(runner.calls))
    assert all(calls == calls_by_run[0] for calls in calls_by_run)


def test_scheduler_rejects_non_positive_configuration() -> None:
    runner = FakeStepRunner()
    with pytest.raises(ValueError):
        GraphScheduler(runner, max_concurrent_steps_per_workflow=0)
    with pytest.raises(ValueError):
        GraphScheduler(runner, max_concurrent_per_agent_type=0)
    with pytest.raises(ValueError):
        GraphScheduler(runner, default_step_timeout_seconds=0)


# ---------------------------------------------------------------------------
# Fix 1: the state machine is real — GraphScheduler validates every transition
# it makes through app.engine.workflow.state_machine. If the wiring were
# wrong (an illegal transition attempted), these calls would raise
# InvalidGraphStateTransition and the test itself would fail with that
# unhandled exception — so "completes normally with the expected status" is
# itself meaningful proof the transitions taken were legal.
# ---------------------------------------------------------------------------


async def test_successful_run_follows_the_full_planning_to_succeeded_lifecycle() -> None:
    runner = FakeStepRunner()
    scheduler = GraphScheduler(runner)
    sink = RecordingStateSink()
    definition = _definition([_step(key="a"), _step(key="b", depends_on=["a"])])

    result = await scheduler.run(definition, workflow_id="wf-lifecycle", sink=sink)

    assert result.status is GraphWorkflowStatus.SUCCEEDED
    event_types = [event.event_type for event in sink.events]
    # Relative order: started, planning, running all precede succeeded.
    assert event_types.index("workflow.started") < event_types.index("workflow.planning")
    assert event_types.index("workflow.planning") < event_types.index("workflow.running")
    assert event_types.index("workflow.running") < event_types.index("workflow.succeeded")
    assert event_types[-1] == "workflow.succeeded"


async def test_cancellation_before_run_begins_follows_the_cancelling_lifecycle() -> None:
    runner = FakeStepRunner()
    scheduler = GraphScheduler(runner)
    sink = RecordingStateSink()
    cancellation = CancellationToken()
    cancellation.cancel()  # cancelled before scheduler.run() is ever awaited
    definition = _definition([_step(key="a")])

    result = await scheduler.run(
        definition, workflow_id="wf-precancelled", cancellation=cancellation, sink=sink
    )

    assert result.status is GraphWorkflowStatus.CANCELLED
    assert result.step_outcomes["a"].status is GraphStepStatus.CANCELLED
    assert runner.calls == []
    event_types = [event.event_type for event in sink.events]
    assert event_types.index("workflow.started") < event_types.index("workflow.planning")
    assert event_types.index("workflow.planning") < event_types.index("workflow.cancelling")
    assert event_types.index("workflow.cancelling") < event_types.index("workflow.cancelled")
    # The RUNNING phase is never reached at all when already cancelled.
    assert "workflow.running" not in event_types


async def test_failed_run_completes_without_raising_an_invalid_transition() -> None:
    runner = FakeStepRunner(failures={"a"})
    scheduler = GraphScheduler(runner)
    definition = _definition([_step(key="a"), _step(key="independent")])
    result = await scheduler.run(definition, workflow_id="wf-failed-lifecycle")
    assert result.status is GraphWorkflowStatus.FAILED


async def test_cancelled_mid_flight_completes_without_raising_an_invalid_transition() -> None:
    release_a = asyncio.Event()
    runner = FakeStepRunner(release_events={"a": release_a})
    scheduler = GraphScheduler(runner)
    cancellation = CancellationToken()
    definition = _definition([_step(key="a")])

    run_task = asyncio.ensure_future(
        scheduler.run(definition, workflow_id="wf-cancel-lifecycle", cancellation=cancellation)
    )
    await asyncio.sleep(0.02)
    cancellation.cancel()
    release_a.set()
    result = await run_task
    assert result.status is GraphWorkflowStatus.CANCELLED


# ---------------------------------------------------------------------------
# Fix 2: previous_outputs is scoped to direct dependencies only.
# ---------------------------------------------------------------------------


async def test_step_receives_only_its_direct_dependencies_outputs() -> None:
    # Diamond: a -> b, a -> c, b & c -> d. d must see only b and c's output,
    # never a's, even though a succeeded earlier in the same run.
    runner = FakeStepRunner(outputs={"a": {"from": "a"}, "b": {"from": "b"}, "c": {"from": "c"}})
    scheduler = GraphScheduler(runner)
    definition = _definition(
        [
            _step(key="a"),
            _step(key="b", depends_on=["a"]),
            _step(key="c", depends_on=["a"]),
            _step(key="d", depends_on=["b", "c"]),
        ]
    )
    result = await scheduler.run(definition, workflow_id="wf-scoped-outputs")
    assert result.status is GraphWorkflowStatus.SUCCEEDED

    seen_by_d = runner.previous_outputs_seen["d"]
    assert set(seen_by_d.keys()) == {"b", "c"}
    assert "a" not in seen_by_d
    assert seen_by_d["b"] == {"from": "b"}
    assert seen_by_d["c"] == {"from": "c"}


async def test_root_step_receives_no_previous_outputs() -> None:
    runner = FakeStepRunner()
    scheduler = GraphScheduler(runner)
    definition = _definition([_step(key="a")])
    await scheduler.run(definition, workflow_id="wf-root-outputs")
    assert runner.previous_outputs_seen["a"] == {}


# ---------------------------------------------------------------------------
# Fix 3: the failure-triggered skip cascade is deterministic, ordered by
# workflow declaration order — not set iteration order.
# ---------------------------------------------------------------------------


async def test_skip_cascade_is_ordered_by_declaration_order_not_alphabetically() -> None:
    # Declared deliberately out of alphabetical order: z, m, b. If the skip
    # cascade were driven by set iteration (as it was before this fix), this
    # order would be arbitrary/hash-dependent instead of z, m, b.
    runner = FakeStepRunner(failures={"a"})
    scheduler = GraphScheduler(runner)
    sink = RecordingStateSink()
    definition = _definition(
        [
            _step(key="a"),
            _step(key="z", depends_on=["a"]),
            _step(key="m", depends_on=["a"]),
            _step(key="b", depends_on=["a"]),
        ]
    )
    result = await scheduler.run(definition, workflow_id="wf-skip-order", sink=sink)

    assert result.status is GraphWorkflowStatus.FAILED
    skip_events = [event for event in sink.events if event.event_type == "step.skipped"]
    assert [event.step_id for event in skip_events] == ["z", "m", "b"]
    # Sequence numbers assigned to those events follow the same order.
    assert [event.sequence_number for event in skip_events] == sorted(
        event.sequence_number for event in skip_events
    )


async def test_skip_cascade_ordering_is_reproducible_across_runs() -> None:
    definition = _definition(
        [
            _step(key="a"),
            _step(key="z", depends_on=["a"]),
            _step(key="m", depends_on=["a"]),
            _step(key="b", depends_on=["a"]),
        ]
    )
    orders: list[list[str]] = []
    for _ in range(5):
        runner = FakeStepRunner(failures={"a"})
        scheduler = GraphScheduler(runner)
        sink = RecordingStateSink()
        await scheduler.run(definition, workflow_id="wf-skip-repro", sink=sink)
        skip_order = [event.step_id for event in sink.events if event.event_type == "step.skipped"]
        orders.append(skip_order)
    assert all(order == orders[0] for order in orders)


# ---------------------------------------------------------------------------
# Fix 4: an unexpected (non-StepRunnerError) runner exception fails only
# that step; the scheduler itself never crashes.
# ---------------------------------------------------------------------------


async def test_unexpected_runner_exception_fails_only_that_step() -> None:
    runner = FakeStepRunner(crashes={"a"})
    scheduler = GraphScheduler(runner)
    definition = _definition(
        [
            _step(key="a"),
            _step(key="descendant", depends_on=["a"]),
            _step(key="independent"),
        ]
    )
    result = await scheduler.run(definition, workflow_id="wf-crash")

    assert result.status is GraphWorkflowStatus.FAILED
    assert result.step_outcomes["a"].status is GraphStepStatus.FAILED
    assert "boom" in (result.step_outcomes["a"].error_message or "")
    assert result.step_outcomes["descendant"].status is GraphStepStatus.SKIPPED
    assert result.step_outcomes["independent"].status is GraphStepStatus.SUCCEEDED
    assert "independent" in runner.calls


# ---------------------------------------------------------------------------
# Fix 5: cancellation edge cases.
# ---------------------------------------------------------------------------


async def test_repeated_cancellation_is_idempotent() -> None:
    release_a = asyncio.Event()
    runner = FakeStepRunner(release_events={"a": release_a})
    scheduler = GraphScheduler(runner)
    cancellation = CancellationToken()
    definition = _definition([_step(key="a")])

    run_task = asyncio.ensure_future(
        scheduler.run(definition, workflow_id="wf-repeat-cancel", cancellation=cancellation)
    )
    await asyncio.sleep(0.02)
    cancellation.cancel()
    cancellation.cancel()
    cancellation.cancel()
    release_a.set()
    result = await run_task

    assert result.status is GraphWorkflowStatus.CANCELLED
    # Cancelling again after completion must not raise either.
    cancellation.cancel()
    assert cancellation.is_cancelled is True


async def test_no_dependent_work_begins_after_cancellation_in_a_wide_graph() -> None:
    release_a = asyncio.Event()
    runner = FakeStepRunner(release_events={"a": release_a})
    scheduler = GraphScheduler(runner)
    cancellation = CancellationToken()
    definition = _definition(
        [
            _step(key="a"),
            _step(key="b1", depends_on=["a"]),
            _step(key="b2", depends_on=["a"]),
            _step(key="b3", depends_on=["a"]),
            _step(key="c1", depends_on=["b1"]),
            _step(key="c2", depends_on=["b2"]),
        ]
    )
    run_task = asyncio.ensure_future(
        scheduler.run(definition, workflow_id="wf-wide-cancel", cancellation=cancellation)
    )
    await asyncio.sleep(0.02)
    cancellation.cancel()
    release_a.set()
    result = await run_task

    assert result.status is GraphWorkflowStatus.CANCELLED
    for key in ("b1", "b2", "b3", "c1", "c2"):
        assert key not in runner.calls
        assert result.step_outcomes[key].status is GraphStepStatus.CANCELLED


async def test_no_orphan_tasks_remain_after_cancellation() -> None:
    release_a = asyncio.Event()
    runner = FakeStepRunner(release_events={"a": release_a})
    scheduler = GraphScheduler(runner)
    cancellation = CancellationToken()
    definition = _definition([_step(key="a"), _step(key="b", depends_on=["a"])])

    tasks_before = asyncio.all_tasks()
    run_task = asyncio.ensure_future(
        scheduler.run(definition, workflow_id="wf-orphan-check", cancellation=cancellation)
    )
    await asyncio.sleep(0.02)
    cancellation.cancel()
    release_a.set()
    await run_task
    # Give any fire-and-forget cancellation bookkeeping one more loop turn.
    await asyncio.sleep(0)

    tasks_after = asyncio.all_tasks()
    leaked = (tasks_after - tasks_before) - {run_task}
    still_running = {task for task in leaked if not task.done()}
    assert still_running == set(), f"orphan tasks still running: {still_running}"


# ---------------------------------------------------------------------------
# Fix 6: additional DAG coverage.
# ---------------------------------------------------------------------------


async def test_empty_workflow_succeeds_with_no_steps() -> None:
    runner = FakeStepRunner()
    scheduler = GraphScheduler(runner)
    definition = _definition([])
    result = await scheduler.run(definition, workflow_id="wf-empty")
    assert result.status is GraphWorkflowStatus.SUCCEEDED
    assert result.step_outcomes == {}
    assert runner.calls == []


async def test_two_disconnected_multi_step_branches_run_independently() -> None:
    runner = FakeStepRunner()
    scheduler = GraphScheduler(runner)
    definition = _definition(
        [
            _step(key="a1"),
            _step(key="a2", depends_on=["a1"]),
            _step(key="b1"),
            _step(key="b2", depends_on=["b1"]),
        ]
    )
    result = await scheduler.run(definition, workflow_id="wf-disconnected")
    assert result.status is GraphWorkflowStatus.SUCCEEDED
    assert all(
        result.step_outcomes[key].status is GraphStepStatus.SUCCEEDED
        for key in ("a1", "a2", "b1", "b2")
    )
    # Each branch's internal order is respected independently.
    assert runner.calls.index("a1") < runner.calls.index("a2")
    assert runner.calls.index("b1") < runner.calls.index("b2")


async def test_no_step_is_ever_scheduled_more_than_once() -> None:
    runner = FakeStepRunner(
        delays={"a": 0.01, "b": 0.02, "c": 0.01},
    )
    scheduler = GraphScheduler(runner, max_concurrent_steps_per_workflow=10)
    definition = _definition(
        [
            _step(key="a"),
            _step(key="b"),
            _step(key="c", depends_on=["a", "b"]),
            _step(key="d", depends_on=["c"]),
        ]
    )
    result = await scheduler.run(definition, workflow_id="wf-no-dup-schedule")
    assert result.status is GraphWorkflowStatus.SUCCEEDED
    assert len(runner.calls) == len(set(runner.calls))
    assert sorted(runner.calls) == ["a", "b", "c", "d"]
