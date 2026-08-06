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
