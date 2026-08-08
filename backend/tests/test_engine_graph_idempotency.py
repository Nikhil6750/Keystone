"""Tests for `IdempotentExecutionGuard`: duplicate-execution protection for
repeated calls sharing an idempotency key."""

import asyncio

import pytest

from app.engine.workflow.idempotency import IdempotentExecutionGuard


async def test_completed_key_returns_the_cached_result_without_rerunning() -> None:
    guard: IdempotentExecutionGuard[int] = IdempotentExecutionGuard()
    call_count = 0

    async def factory() -> int:
        nonlocal call_count
        call_count += 1
        return 42

    first = await guard.run_once("key-1", factory)
    second = await guard.run_once("key-1", factory)

    assert first == 42
    assert second == 42
    assert call_count == 1


async def test_concurrent_calls_with_the_same_key_share_one_execution() -> None:
    guard: IdempotentExecutionGuard[int] = IdempotentExecutionGuard()
    call_count = 0
    release = asyncio.Event()

    async def factory() -> int:
        nonlocal call_count
        call_count += 1
        await release.wait()
        return 7

    task_a = asyncio.ensure_future(guard.run_once("shared", factory))
    task_b = asyncio.ensure_future(guard.run_once("shared", factory))
    await asyncio.sleep(0.01)
    release.set()
    result_a, result_b = await asyncio.gather(task_a, task_b)

    assert result_a == result_b == 7
    assert call_count == 1


async def test_different_keys_run_independently() -> None:
    guard: IdempotentExecutionGuard[str] = IdempotentExecutionGuard()

    async def make(value: str) -> str:
        return value

    result_a = await guard.run_once("a", lambda: make("A"))
    result_b = await guard.run_once("b", lambda: make("B"))

    assert result_a == "A"
    assert result_b == "B"


async def test_a_failed_execution_is_not_cached_and_can_be_retried() -> None:
    guard: IdempotentExecutionGuard[int] = IdempotentExecutionGuard()
    attempts = 0

    async def factory() -> int:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("boom")
        return 99

    with pytest.raises(RuntimeError):
        await guard.run_once("retry-key", factory)

    result = await guard.run_once("retry-key", factory)
    assert result == 99
    assert attempts == 2


async def test_concurrent_calls_sharing_a_failed_key_all_see_the_same_exception() -> None:
    guard: IdempotentExecutionGuard[int] = IdempotentExecutionGuard()
    release = asyncio.Event()

    async def factory() -> int:
        await release.wait()
        raise ValueError("shared failure")

    task_a = asyncio.ensure_future(guard.run_once("fail-key", factory))
    task_b = asyncio.ensure_future(guard.run_once("fail-key", factory))
    await asyncio.sleep(0.01)
    release.set()

    with pytest.raises(ValueError):
        await task_a
    with pytest.raises(ValueError):
        await task_b


# --- Fix 3: bounded LRU result cache ---------------------------------------


def test_max_cached_results_must_be_positive() -> None:
    with pytest.raises(ValueError):
        IdempotentExecutionGuard(max_cached_results=0)
    with pytest.raises(ValueError):
        IdempotentExecutionGuard(max_cached_results=-1)


async def test_cache_evicts_the_least_recently_used_entry_over_capacity() -> None:
    guard: IdempotentExecutionGuard[str] = IdempotentExecutionGuard(max_cached_results=2)

    async def make(value: str) -> str:
        return value

    await guard.run_once("a", lambda: make("A"))
    await guard.run_once("b", lambda: make("B"))
    await guard.run_once("c", lambda: make("C"))  # evicts "a" (least recently used)

    assert "a" not in guard._results
    assert "b" in guard._results
    assert "c" in guard._results

    reran = False

    async def rerun_a() -> str:
        nonlocal reran
        reran = True
        return "A-again"

    result = await guard.run_once("a", rerun_a)
    assert reran is True
    assert result == "A-again"


async def test_reading_a_cached_entry_protects_it_from_eviction() -> None:
    guard: IdempotentExecutionGuard[str] = IdempotentExecutionGuard(max_cached_results=2)

    async def make(value: str) -> str:
        return value

    await guard.run_once("a", lambda: make("A"))
    await guard.run_once("b", lambda: make("B"))
    await guard.run_once("a", lambda: make("SHOULD_NOT_RUN"))  # touch "a" -> most recently used
    await guard.run_once("c", lambda: make("C"))  # now evicts "b", not "a"

    assert "a" in guard._results
    assert "b" not in guard._results
    assert "c" in guard._results


async def test_in_flight_executions_are_never_evicted() -> None:
    guard: IdempotentExecutionGuard[str] = IdempotentExecutionGuard(max_cached_results=1)
    release = asyncio.Event()

    async def slow(value: str) -> str:
        await release.wait()
        return value

    # Two keys in flight at once, over the cache's completed-result capacity
    # of 1 — capacity only bounds *completed* results, never in-flight work.
    task_a = asyncio.ensure_future(guard.run_once("a", lambda: slow("A")))
    task_b = asyncio.ensure_future(guard.run_once("b", lambda: slow("B")))
    await asyncio.sleep(0.01)
    assert len(guard._in_flight) == 2

    release.set()
    result_a, result_b = await asyncio.gather(task_a, task_b)
    assert result_a == "A"
    assert result_b == "B"


# --- Fix 4: cancellation isolation between callers sharing one key --------


async def test_cancelling_one_caller_does_not_cancel_the_shared_execution() -> None:
    guard: IdempotentExecutionGuard[str] = IdempotentExecutionGuard()
    call_count = 0
    release = asyncio.Event()

    async def factory() -> str:
        nonlocal call_count
        call_count += 1
        await release.wait()
        return "done"

    task_a = asyncio.ensure_future(guard.run_once("shared", factory))
    task_b = asyncio.ensure_future(guard.run_once("shared", factory))
    await asyncio.sleep(0.01)

    task_a.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task_a

    # B was never cancelled and must still receive the real result once the
    # shared execution completes.
    release.set()
    result_b = await task_b
    assert result_b == "done"
    assert call_count == 1


async def test_cancelling_the_owner_caller_still_lets_other_waiters_succeed() -> None:
    """The caller whose task happens to be running the shared factory (the
    "owner") can itself be cancelled without cancelling the shared execution
    other callers depend on."""
    guard: IdempotentExecutionGuard[str] = IdempotentExecutionGuard()
    release = asyncio.Event()

    async def factory() -> str:
        await release.wait()
        return "done"

    owner = asyncio.ensure_future(guard.run_once("shared", factory))
    await asyncio.sleep(0.01)
    waiter = asyncio.ensure_future(guard.run_once("shared", factory))
    await asyncio.sleep(0.01)

    owner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner

    release.set()
    result = await waiter
    assert result == "done"


async def test_no_orphan_task_remains_after_cancelling_one_of_two_waiters() -> None:
    guard: IdempotentExecutionGuard[str] = IdempotentExecutionGuard()
    release = asyncio.Event()

    async def factory() -> str:
        await release.wait()
        return "done"

    tasks_before = asyncio.all_tasks()
    task_a = asyncio.ensure_future(guard.run_once("shared", factory))
    task_b = asyncio.ensure_future(guard.run_once("shared", factory))
    await asyncio.sleep(0.01)

    task_a.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task_a
    release.set()
    await task_b
    await asyncio.sleep(0)

    tasks_after = asyncio.all_tasks()
    leaked = (tasks_after - tasks_before) - {task_a, task_b}
    still_running = {task for task in leaked if not task.done()}
    assert still_running == set(), f"orphan tasks still running: {still_running}"
