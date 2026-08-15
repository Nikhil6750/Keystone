"""Tests for the standardized execution-failure taxonomy."""

from app.adapters.exceptions import (
    AgentAuthenticationError,
    AgentConfigurationError,
    AgentOutputError,
    AgentPermissionError,
    AgentProcessError,
    AgentTimeoutError,
    AgentUnavailableError,
    AgentUsageLimitError,
)
from app.contracts.errors import (
    RETRYABLE_FAILURE_CATEGORIES,
    FailureCategory,
    classify_legacy_error_type,
    is_legacy_error_type_retryable,
)


def test_known_legacy_error_types_map_to_stable_categories() -> None:
    assert classify_legacy_error_type("AGENT_TIMEOUT") is FailureCategory.TIMEOUT
    assert (
        classify_legacy_error_type("AGENT_AUTHENTICATION_ERROR")
        is FailureCategory.AUTHENTICATION_FAILURE
    )
    assert classify_legacy_error_type("CIRCUIT_BREAKER_OPEN") is FailureCategory.CIRCUIT_OPEN
    assert classify_legacy_error_type("AGENT_USAGE_LIMIT_ERROR") is FailureCategory.RATE_LIMITED


def test_unknown_legacy_error_type_maps_to_unknown_not_a_crash() -> None:
    assert classify_legacy_error_type("SOME_FUTURE_ERROR_CODE") is FailureCategory.UNKNOWN


def test_authentication_and_validation_failures_are_not_marked_retryable() -> None:
    assert FailureCategory.AUTHENTICATION_FAILURE not in RETRYABLE_FAILURE_CATEGORIES
    assert FailureCategory.VALIDATION_FAILURE not in RETRYABLE_FAILURE_CATEGORIES
    assert FailureCategory.CANCELLED not in RETRYABLE_FAILURE_CATEGORIES


def test_timeout_and_rate_limited_are_marked_retryable() -> None:
    assert FailureCategory.TIMEOUT in RETRYABLE_FAILURE_CATEGORIES
    assert FailureCategory.RATE_LIMITED in RETRYABLE_FAILURE_CATEGORIES


# --- is_legacy_error_type_retryable: the canonical retry-policy decision ---


def test_canonical_retry_policy_matches_every_live_adapter_exception() -> None:
    """Cross-checks the canonical policy against the actual live adapter
    exceptions' `retryable` flags (not a second hardcoded copy of them), so
    this fails loudly if a future adapter change silently diverges from the
    policy the additive async retry layer relies on."""
    adapter_exceptions = [
        AgentUnavailableError("x"),
        AgentConfigurationError("x"),
        AgentTimeoutError("x"),
        AgentProcessError("x"),
        AgentOutputError("x"),
        AgentAuthenticationError("x"),
        AgentUsageLimitError("x"),
        AgentPermissionError("x"),
    ]
    for exc in adapter_exceptions:
        canonical = is_legacy_error_type_retryable(exc.error_type)
        assert canonical == exc.retryable, (
            f"{exc.error_type}: canonical policy says {canonical}, "
            f"live adapter exception says {exc.retryable}"
        )


def test_agent_unavailable_is_not_retryable() -> None:
    # This is the case that used to disagree with RETRYABLE_FAILURE_CATEGORIES
    # (which buckets it into the broadly-retryable PROVIDER_ERROR).
    assert is_legacy_error_type_retryable("AGENT_UNAVAILABLE") is False


def test_agent_usage_limit_error_is_not_retryable() -> None:
    # Also used to disagree (bucketed into the broadly-retryable RATE_LIMITED)
    # — no retry-after-aware scheduling exists yet, so an immediate retry
    # would just fail identically.
    assert is_legacy_error_type_retryable("AGENT_USAGE_LIMIT_ERROR") is False


def test_authentication_failures_are_not_retryable() -> None:
    assert is_legacy_error_type_retryable("AGENT_AUTHENTICATION_ERROR") is False
    assert is_legacy_error_type_retryable("AGENT_PERMISSION_ERROR") is False


def test_validation_failures_are_not_retryable() -> None:
    assert is_legacy_error_type_retryable("AGENT_CONFIGURATION_ERROR") is False
    assert is_legacy_error_type_retryable("INVALID_EXECUTOR_OUTPUT") is False


def test_transient_provider_failures_are_retryable() -> None:
    assert is_legacy_error_type_retryable("AGENT_TIMEOUT") is True
    assert is_legacy_error_type_retryable("AGENT_PROCESS_ERROR") is True
    assert is_legacy_error_type_retryable("AGENT_OUTPUT_ERROR") is True


def test_unrecognized_error_type_defaults_to_retryable() -> None:
    assert is_legacy_error_type_retryable("SOME_FUTURE_ERROR_CODE") is True
