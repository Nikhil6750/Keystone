"""A per-run cancellation signal, isolated to one `GraphScheduler.run()` call."""

import asyncio


class CancellationToken:
    """Cooperative cancellation signal for one workflow run.

    Never shared across workflow runs — each `GraphScheduler.run()` call gets
    its own token (or one is created for it), so cancelling one workflow can
    never affect another concurrently running workflow.
    """

    def __init__(self) -> None:
        self._event = asyncio.Event()

    def cancel(self) -> None:
        """Signal cancellation. Idempotent."""
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        """Suspend until `cancel()` is called."""
        await self._event.wait()


__all__ = ["CancellationToken"]
