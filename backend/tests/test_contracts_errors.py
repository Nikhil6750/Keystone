"""Tests for the standardized execution-failure taxonomy."""

from app.contracts.errors import (
    RETRYABLE_FAILURE_CATEGORIES,
    FailureCategory,
    classify_legacy_error_type,
)


def test_known_legacy_error_types_map_to_stable_categories() -> None:
    assert classify_legacy_error_type("AGENT_TIMEOUT") is FailureCategory.TIMEOUT
    assert (
        classify_legacy_error_type("AGENT_AUTHENTICATION_ERROR")
        is FailureCategory.AUTHENTICATION_FAILURE
    )
    assert classify_legacy_error_type("CIRCUIT_BREAKER_OPEN") is FailureCategory.CIRCUIT_OPEN
    assert (
        classify_legacy_error_type("AGENT_USAGE_LIMIT_ERROR") is FailureCategory.RATE_LIMITED
    )


def test_unknown_legacy_error_type_maps_to_unknown_not_a_crash() -> None:
    assert classify_legacy_error_type("SOME_FUTURE_ERROR_CODE") is FailureCategory.UNKNOWN


def test_authentication_and_validation_failures_are_not_marked_retryable() -> None:
    assert FailureCategory.AUTHENTICATION_FAILURE not in RETRYABLE_FAILURE_CATEGORIES
    assert FailureCategory.VALIDATION_FAILURE not in RETRYABLE_FAILURE_CATEGORIES
    assert FailureCategory.CANCELLED not in RETRYABLE_FAILURE_CATEGORIES


def test_timeout_and_rate_limited_are_marked_retryable() -> None:
    assert FailureCategory.TIMEOUT in RETRYABLE_FAILURE_CATEGORIES
    assert FailureCategory.RATE_LIMITED in RETRYABLE_FAILURE_CATEGORIES
