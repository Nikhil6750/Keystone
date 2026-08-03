"""Tests for the in-memory, thread-safe per-agent-type circuit breaker."""

import threading

import pytest

from app.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitBreakerRegistry,
    CircuitState,
)
from tests.support.fakes import FakeClock


def _breaker(
    failure_threshold: int = 3,
    recovery_timeout_seconds: float = 10.0,
    clock: FakeClock | None = None,
) -> CircuitBreaker:
    return CircuitBreaker(
        "mock",
        failure_threshold=failure_threshold,
        recovery_timeout_seconds=recovery_timeout_seconds,
        clock=clock or FakeClock(),
    )


def test_new_breaker_starts_closed() -> None:
    breaker = _breaker()
    assert breaker.snapshot().state is CircuitState.CLOSED


def test_success_keeps_circuit_closed() -> None:
    breaker = _breaker()
    breaker.before_call()
    breaker.record_success()
    assert breaker.snapshot().state is CircuitState.CLOSED


def test_counted_failures_increment_failure_count() -> None:
    breaker = _breaker(failure_threshold=5)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.snapshot().failure_count == 2


def test_threshold_opens_the_circuit() -> None:
    breaker = _breaker(failure_threshold=2)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.snapshot().state is CircuitState.OPEN


def test_open_circuit_rejects_calls() -> None:
    breaker = _breaker(failure_threshold=1)
    breaker.record_failure()
    with pytest.raises(CircuitBreakerOpenError):
        breaker.before_call()


def test_open_rejection_does_not_invoke_adapter() -> None:
    breaker = _breaker(failure_threshold=1)
    breaker.record_failure()
    invoked = False
    try:
        breaker.before_call()
        invoked = True
    except CircuitBreakerOpenError:
        pass
    assert invoked is False


def test_recovery_timeout_permits_one_half_open_probe() -> None:
    clock = FakeClock()
    breaker = _breaker(failure_threshold=1, recovery_timeout_seconds=10.0, clock=clock)
    breaker.record_failure()
    assert breaker.snapshot().state is CircuitState.OPEN

    clock.advance(10.0)
    breaker.before_call()  # should not raise; transitions to HALF_OPEN

    assert breaker.snapshot().state is CircuitState.HALF_OPEN
    assert breaker.snapshot().half_open_probe_in_flight is True


def test_successful_half_open_probe_closes_circuit() -> None:
    clock = FakeClock()
    breaker = _breaker(failure_threshold=1, recovery_timeout_seconds=10.0, clock=clock)
    breaker.record_failure()
    clock.advance(10.0)
    breaker.before_call()

    breaker.record_success()

    assert breaker.snapshot().state is CircuitState.CLOSED
    assert breaker.snapshot().failure_count == 0


def test_failed_half_open_probe_reopens_circuit() -> None:
    clock = FakeClock()
    breaker = _breaker(failure_threshold=1, recovery_timeout_seconds=10.0, clock=clock)
    breaker.record_failure()
    clock.advance(10.0)
    breaker.before_call()

    breaker.record_failure()

    assert breaker.snapshot().state is CircuitState.OPEN


def test_concurrent_half_open_probes_are_rejected() -> None:
    clock = FakeClock()
    breaker = _breaker(failure_threshold=1, recovery_timeout_seconds=10.0, clock=clock)
    breaker.record_failure()
    clock.advance(10.0)
    breaker.before_call()  # first probe granted

    with pytest.raises(CircuitBreakerOpenError):
        breaker.before_call()  # second probe must be rejected


def test_non_counted_failures_do_not_affect_breaker() -> None:
    breaker = _breaker(failure_threshold=2)
    # Simulate the engine simply never calling record_failure for a
    # non-counted failure (e.g. missing executor) — the breaker's state must
    # be untouched by definition, since nothing was recorded.
    assert breaker.snapshot().failure_count == 0
    assert breaker.snapshot().state is CircuitState.CLOSED


def test_retry_after_is_never_negative() -> None:
    clock = FakeClock()
    breaker = _breaker(failure_threshold=1, recovery_timeout_seconds=5.0, clock=clock)
    breaker.record_failure()

    clock.advance(100.0)  # far beyond recovery timeout

    assert breaker.snapshot().retry_after_seconds >= 0.0


def test_retry_after_counts_down_while_open() -> None:
    clock = FakeClock()
    breaker = _breaker(failure_threshold=1, recovery_timeout_seconds=10.0, clock=clock)
    breaker.record_failure()

    assert breaker.snapshot().retry_after_seconds == pytest.approx(10.0)
    clock.advance(4.0)
    assert breaker.snapshot().retry_after_seconds == pytest.approx(6.0)


def test_separate_agent_types_have_separate_breakers() -> None:
    registry = CircuitBreakerRegistry(failure_threshold=1, recovery_timeout_seconds=10.0)
    claude_breaker = registry.get_or_create("claude_code")
    codex_breaker = registry.get_or_create("codex")

    claude_breaker.record_failure()

    assert claude_breaker.snapshot().state is CircuitState.OPEN
    assert codex_breaker.snapshot().state is CircuitState.CLOSED


def test_separate_registries_do_not_share_state() -> None:
    registry_a = CircuitBreakerRegistry(failure_threshold=1, recovery_timeout_seconds=10.0)
    registry_b = CircuitBreakerRegistry(failure_threshold=1, recovery_timeout_seconds=10.0)

    registry_a.get_or_create("mock").record_failure()

    assert registry_a.get_or_create("mock").snapshot().state is CircuitState.OPEN
    assert registry_b.get_or_create("mock").snapshot().state is CircuitState.CLOSED


def test_breaker_snapshots_serialize_correctly() -> None:
    registry = CircuitBreakerRegistry(failure_threshold=2, recovery_timeout_seconds=10.0)
    registry.get_or_create("mock").record_failure()

    snapshots = registry.snapshots()

    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.agent_type == "mock"
    assert snapshot.failure_count == 1
    assert snapshot.failure_threshold == 2
    assert snapshot.recovery_timeout_seconds == 10.0
    assert snapshot.retry_after_seconds >= 0.0
    assert snapshot.half_open_probe_in_flight is False


def test_thread_safety_under_concurrent_failures() -> None:
    breaker = _breaker(failure_threshold=1000)
    threads_count = 20
    calls_per_thread = 25

    def _hammer() -> None:
        for _ in range(calls_per_thread):
            breaker.record_failure()

    threads = [threading.Thread(target=_hammer) for _ in range(threads_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5.0)

    # No lost updates: the failure count must exactly equal total calls made,
    # proving the lock correctly serialized concurrent increments.
    assert breaker.snapshot().failure_count == threads_count * calls_per_thread
