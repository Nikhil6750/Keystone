"""Injectable sleep, so retry tests never actually wait."""

import time
from typing import Protocol


class Sleeper(Protocol):
    """Something that can pause execution for a bounded delay."""

    def sleep(self, seconds: float) -> None: ...


class RealSleeper:
    """The real sleeper, backed by `time.sleep()`."""

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)
