"""Bounded exponential backoff for step-attempt retries."""

import random
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RetryPolicy:
    """Computes the delay before the next retry attempt.

    `delay = min(max_delay, base_delay * 2^(failed_attempt_number - 1))`, plus
    optional bounded jitter. The jitter provider is injectable so tests stay
    deterministic; it must return a value in `[0.0, 1.0)`, same as `random.random`.
    """

    base_delay_seconds: float
    max_delay_seconds: float
    jitter_ratio: float = 0.0
    jitter_provider: Callable[[], float] = field(default=random.random)

    def __post_init__(self) -> None:
        if self.base_delay_seconds < 0:
            raise ValueError("base_delay_seconds must not be negative")
        if self.max_delay_seconds < 0:
            raise ValueError("max_delay_seconds must not be negative")
        if not 0.0 <= self.jitter_ratio <= 1.0:
            raise ValueError("jitter_ratio must be between 0.0 and 1.0")

    def compute_delay(self, failed_attempt_number: int) -> float:
        """The delay before retrying, given the 1-indexed attempt number that just failed.

        Never negative; never exceeds `max_delay_seconds`.
        """
        raw_delay: float = self.base_delay_seconds * (2 ** (failed_attempt_number - 1))
        delay: float = min(self.max_delay_seconds, raw_delay)
        if self.jitter_ratio > 0:
            jitter: float = delay * self.jitter_ratio * self.jitter_provider()
            delay = min(self.max_delay_seconds, delay + jitter)
        return max(0.0, delay)
