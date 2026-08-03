"""Retry policies and circuit breakers.

`clock.py`/`sleeper.py` are the injectable time primitives so tests never
wait or depend on real time. `retry.py` implements bounded exponential
backoff (`RetryPolicy`). `circuit_breaker.py` implements a thread-safe,
in-memory, per-agent-type `CircuitBreaker` (CLOSED/OPEN/HALF_OPEN) and the
application-scoped `CircuitBreakerRegistry` that owns one breaker per
normalized agent type.
"""
