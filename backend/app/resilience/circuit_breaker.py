"""Per-agent-type circuit breaker: in-memory, thread-safe, same-day prototype scope.

State does not survive an application restart — restarting the process is the
prototype's acceptable manual reset.
"""

import logging
import threading
from dataclasses import dataclass
from enum import StrEnum

from app.resilience.clock import Clock, SystemClock

logger = logging.getLogger(__name__)


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpenError(Exception):
    """Raised when a call is rejected because its circuit is open."""

    def __init__(self, agent_type: str, retry_after_seconds: float) -> None:
        self.agent_type = agent_type
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"circuit breaker open for agent type '{agent_type}'")


@dataclass(frozen=True)
class CircuitBreakerSnapshot:
    """A safe, immutable, API-facing snapshot of one circuit breaker's state."""

    agent_type: str
    state: CircuitState
    failure_count: int
    failure_threshold: int
    recovery_timeout_seconds: float
    retry_after_seconds: float
    half_open_probe_in_flight: bool


class CircuitBreaker:
    """One agent type's circuit breaker.

    Thread-safe via a single lock guarding all mutable state. The lock is held
    only for short bookkeeping sections — never while an external agent call
    is in flight.
    """

    def __init__(
        self,
        agent_type: str,
        *,
        failure_threshold: int,
        recovery_timeout_seconds: float,
        clock: Clock | None = None,
    ) -> None:
        self._agent_type = agent_type
        self._failure_threshold = failure_threshold
        self._recovery_timeout_seconds = recovery_timeout_seconds
        self._clock: Clock = clock or SystemClock()
        self._lock = threading.Lock()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at: float | None = None
        self._half_open_probe_in_flight = False

    def before_call(self) -> None:
        """Raise `CircuitBreakerOpenError` if this call must not proceed.

        Reserves the single half-open probe slot when permitting a probe.
        """
        with self._lock:
            if self._state is CircuitState.CLOSED:
                return

            if self._state is CircuitState.OPEN:
                elapsed = self._clock.monotonic() - (self._opened_at or 0.0)
                if elapsed >= self._recovery_timeout_seconds:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_probe_in_flight = True
                    logger.info("circuit_breaker_half_open agent_type=%s", self._agent_type)
                    return
                self._reject_locked()

            elif self._half_open_probe_in_flight:
                self._reject_locked()
            else:
                self._half_open_probe_in_flight = True

    def record_success(self) -> None:
        """Record a successful call, closing the circuit."""
        with self._lock:
            changed = self._state is not CircuitState.CLOSED
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._opened_at = None
            self._half_open_probe_in_flight = False
        if changed:
            logger.info("circuit_breaker_closed agent_type=%s", self._agent_type)

    def record_failure(self) -> None:
        """Record a counted failure, possibly opening (or reopening) the circuit."""
        opened = False
        failure_count = 0
        with self._lock:
            if self._state is CircuitState.HALF_OPEN:
                self._half_open_probe_in_flight = False
                self._state = CircuitState.OPEN
                self._opened_at = self._clock.monotonic()
                opened = True
            else:
                self._failure_count += 1
                if (
                    self._failure_count >= self._failure_threshold
                    and self._state is not CircuitState.OPEN
                ):
                    self._state = CircuitState.OPEN
                    self._opened_at = self._clock.monotonic()
                    opened = True
            failure_count = self._failure_count
        if opened:
            logger.warning(
                "circuit_breaker_opened agent_type=%s failure_count=%s failure_threshold=%s",
                self._agent_type,
                failure_count,
                self._failure_threshold,
            )

    def snapshot(self) -> CircuitBreakerSnapshot:
        """A safe, immutable snapshot of the current breaker state."""
        with self._lock:
            return CircuitBreakerSnapshot(
                agent_type=self._agent_type,
                state=self._state,
                failure_count=self._failure_count,
                failure_threshold=self._failure_threshold,
                recovery_timeout_seconds=self._recovery_timeout_seconds,
                retry_after_seconds=self._retry_after_locked(),
                half_open_probe_in_flight=self._half_open_probe_in_flight,
            )

    def _retry_after_locked(self) -> float:
        """Caller must already hold `self._lock`."""
        if self._state is not CircuitState.OPEN or self._opened_at is None:
            return 0.0
        elapsed = self._clock.monotonic() - self._opened_at
        return max(0.0, self._recovery_timeout_seconds - elapsed)

    def _reject_locked(self) -> None:
        """Caller must already hold `self._lock`. Always raises."""
        retry_after = self._retry_after_locked()
        logger.info(
            "circuit_breaker_call_rejected agent_type=%s state=%s retry_after_seconds=%.3f",
            self._agent_type,
            self._state.value,
            retry_after,
        )
        raise CircuitBreakerOpenError(self._agent_type, retry_after)


class CircuitBreakerRegistry:
    """One `CircuitBreaker` per normalized agent type.

    Not a module-level singleton: create one instance per application (via
    lifespan state) or per test. Thread-safe; separate instances never share
    breaker state.
    """

    def __init__(
        self,
        *,
        failure_threshold: int,
        recovery_timeout_seconds: float,
        clock: Clock | None = None,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout_seconds = recovery_timeout_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._breakers: dict[str, CircuitBreaker] = {}

    @staticmethod
    def _normalize(agent_type: str) -> str:
        normalized = agent_type.strip().lower()
        if not normalized:
            raise ValueError("agent_type must not be blank")
        return normalized

    def get_or_create(self, agent_type: str) -> CircuitBreaker:
        """Return the breaker for `agent_type`, creating it on first use."""
        normalized = self._normalize(agent_type)
        with self._lock:
            breaker = self._breakers.get(normalized)
            if breaker is None:
                breaker = CircuitBreaker(
                    normalized,
                    failure_threshold=self._failure_threshold,
                    recovery_timeout_seconds=self._recovery_timeout_seconds,
                    clock=self._clock,
                )
                self._breakers[normalized] = breaker
            return breaker

    def snapshots(self) -> list[CircuitBreakerSnapshot]:
        """Safe snapshots of every breaker created so far, for API responses."""
        with self._lock:
            breakers = list(self._breakers.values())
        return [breaker.snapshot() for breaker in breakers]
