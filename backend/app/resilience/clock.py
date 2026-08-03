"""Injectable monotonic clock, so circuit-breaker tests never depend on real time."""

import time
from typing import Protocol


class Clock(Protocol):
    """A source of monotonic time, in seconds."""

    def monotonic(self) -> float: ...


class SystemClock:
    """The real clock, backed by `time.monotonic()`."""

    def monotonic(self) -> float:
        return time.monotonic()
