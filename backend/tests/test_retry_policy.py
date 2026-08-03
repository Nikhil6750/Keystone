"""Tests for `RetryPolicy` delay computation."""

import pytest

from app.resilience.retry import RetryPolicy


def test_delay_follows_bounded_exponential_backoff() -> None:
    policy = RetryPolicy(base_delay_seconds=1.0, max_delay_seconds=100.0)

    assert policy.compute_delay(1) == 1.0
    assert policy.compute_delay(2) == 2.0
    assert policy.compute_delay(3) == 4.0
    assert policy.compute_delay(4) == 8.0


def test_delay_never_exceeds_maximum() -> None:
    policy = RetryPolicy(base_delay_seconds=1.0, max_delay_seconds=5.0)

    assert policy.compute_delay(10) == 5.0


def test_delay_is_never_negative() -> None:
    policy = RetryPolicy(base_delay_seconds=0.0, max_delay_seconds=0.0)

    assert policy.compute_delay(1) == 0.0
    assert policy.compute_delay(5) == 0.0


def test_jitter_is_bounded_and_deterministic_with_injected_provider() -> None:
    policy = RetryPolicy(
        base_delay_seconds=1.0,
        max_delay_seconds=10.0,
        jitter_ratio=0.5,
        jitter_provider=lambda: 1.0,
    )

    # delay=1.0, jitter = 1.0 * 0.5 * 1.0 = 0.5 -> total 1.5
    assert policy.compute_delay(1) == 1.5


def test_zero_jitter_provider_yields_base_delay() -> None:
    policy = RetryPolicy(
        base_delay_seconds=2.0,
        max_delay_seconds=10.0,
        jitter_ratio=0.5,
        jitter_provider=lambda: 0.0,
    )

    assert policy.compute_delay(1) == 2.0


def test_negative_base_delay_is_rejected() -> None:
    with pytest.raises(ValueError, match="base_delay_seconds"):
        RetryPolicy(base_delay_seconds=-1.0, max_delay_seconds=5.0)


def test_jitter_ratio_out_of_range_is_rejected() -> None:
    with pytest.raises(ValueError, match="jitter_ratio"):
        RetryPolicy(base_delay_seconds=1.0, max_delay_seconds=5.0, jitter_ratio=1.5)
