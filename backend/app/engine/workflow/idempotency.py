"""In-memory idempotency guard for repeated `GraphScheduler.run()`-shaped calls.

Not persisted (in-memory, per-process) — this is the additive layer's
"duplicate execution protection" and "idempotency keys" seam; a future stage
backing this with the database would preserve the same interface.
"""

import asyncio
from collections.abc import Awaitable, Callable


class IdempotentExecutionGuard[T]:
    """Ensures at most one execution runs per idempotency key at a time.

    A duplicate call with a key already in flight awaits and returns the
    same in-flight call's result (or re-raises its exception) rather than
    starting a second execution; a duplicate call with a key that already
    completed returns the cached result immediately without re-running
    anything.
    """

    def __init__(self) -> None:
        self._results: dict[str, T] = {}
        self._in_flight: dict[str, asyncio.Future[T]] = {}

    async def run_once(self, key: str, factory: Callable[[], Awaitable[T]]) -> T:
        if key in self._results:
            return self._results[key]
        if key in self._in_flight:
            return await self._in_flight[key]

        future: asyncio.Future[T] = asyncio.get_running_loop().create_future()
        self._in_flight[key] = future
        try:
            result = await factory()
        except BaseException as exc:
            future.set_exception(exc)
            # This caller already has `exc` directly and raises it below; mark
            # the future's exception retrieved so asyncio doesn't log an
            # "exception was never retrieved" warning when no one else was
            # awaiting it.
            future.exception()
            del self._in_flight[key]
            raise
        self._results[key] = result
        future.set_result(result)
        del self._in_flight[key]
        return result


__all__ = ["IdempotentExecutionGuard"]
