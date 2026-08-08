"""In-memory idempotency guard for repeated `GraphScheduler.run()`-shaped calls.

**This mechanism is process-local only.** It is not restart-safe and does not
provide cross-process idempotency: state lives entirely in this object's
in-memory dicts and is lost on process restart, and it coordinates nothing
across multiple processes or replicas. It is the additive layer's
"duplicate execution protection within one process's uptime" seam; a future
stage backing this with the database (for restart-safe, cross-process
idempotency) would need a different implementation behind the same
`run_once` interface, not an extension of this one.
"""

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any

_DEFAULT_MAX_CACHED_RESULTS = 1000


def _mark_exception_retrieved(task: "asyncio.Task[Any]") -> None:
    """Defensively touch a finished task's exception (if any) so asyncio never
    logs an "exception was never retrieved" warning — regardless of whether
    any external caller's `asyncio.shield()` await actually consumed it (a
    caller whose own wait was cancelled never retrieves it directly)."""
    if not task.cancelled():
        task.exception()


class IdempotentExecutionGuard[T]:
    """Ensures at most one execution runs per idempotency key at a time, with
    a bounded, least-recently-used cache of completed successful results.

    Multiple concurrent callers sharing one key all await the *same*
    underlying execution, run as its own independent task and protected with
    `asyncio.shield()`: cancelling one caller's own wait never cancels the
    shared execution or any other caller waiting on it — it only stops that
    one caller from waiting further. A genuine failure from the shared
    execution (not a cancellation of one particular waiter) still reaches
    every active waiter.

    A duplicate call for a key that already completed successfully returns
    the cached result immediately without re-running anything, until that
    entry is evicted (least-recently-used) once the cache exceeds
    `max_cached_results`. In-flight executions are never eligible for
    eviction — only completed, cached results are. Failures are never
    cached, so a failed key can always be retried on the next call.
    """

    def __init__(self, *, max_cached_results: int = _DEFAULT_MAX_CACHED_RESULTS) -> None:
        if max_cached_results <= 0:
            raise ValueError("max_cached_results must be positive")
        self._max_cached_results = max_cached_results
        self._results: OrderedDict[str, T] = OrderedDict()
        self._in_flight: dict[str, asyncio.Task[T]] = {}

    async def run_once(self, key: str, factory: Callable[[], Awaitable[T]]) -> T:
        if key in self._results:
            self._results.move_to_end(key)
            return self._results[key]

        task = self._in_flight.get(key)
        if task is None:
            task = asyncio.ensure_future(self._execute_and_cache(key, factory))
            task.add_done_callback(_mark_exception_retrieved)
            self._in_flight[key] = task

        # `shield` isolates *this caller's* wait from the shared task: if the
        # coroutine calling `run_once` is itself cancelled, only its own
        # await of the shield raises CancelledError — `task` keeps running
        # to completion in the background for every other waiter.
        return await asyncio.shield(task)

    async def _execute_and_cache(self, key: str, factory: Callable[[], Awaitable[T]]) -> T:
        try:
            result = await factory()
        except BaseException:
            self._in_flight.pop(key, None)
            raise
        self._in_flight.pop(key, None)
        self._results[key] = result
        self._results.move_to_end(key)
        self._evict_if_over_capacity()
        return result

    def _evict_if_over_capacity(self) -> None:
        while len(self._results) > self._max_cached_results:
            self._results.popitem(last=False)


__all__ = ["IdempotentExecutionGuard"]
