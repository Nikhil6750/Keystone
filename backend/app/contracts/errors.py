"""Standardized execution-failure taxonomy shared by adapters, routing, agent
passports and benchmarking.

This is distinct from `app.schemas.errors.APIErrorCode` (the HTTP error
envelope returned by the API layer) and from the existing
`StepExecutionError.error_type` strings each adapter already raises
(`app.adapters.exceptions`). Both of those keep working unchanged;
`classify_legacy_error_type` bridges the existing free-form error-type
strings into this smaller, stable set so routing and passports can reason
about failures without special-casing every adapter's error codes.
"""

from enum import StrEnum


class FailureCategory(StrEnum):
    """A coarse, stable classification of why an agent execution failed."""

    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    AUTHENTICATION_FAILURE = "authentication_failure"
    VALIDATION_FAILURE = "validation_failure"
    RATE_LIMITED = "rate_limited"
    CIRCUIT_OPEN = "circuit_open"
    PROVIDER_ERROR = "provider_error"
    NETWORK_ERROR = "network_error"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    INTERNAL_ERROR = "internal_error"
    UNKNOWN = "unknown"


# A default, best-effort view of which categories are generally worth
# retrying. Individual `StepExecutionError.retryable` flags on the actual
# raised exception remain authoritative for engine retry decisions — this set
# is evidence for routing/passport scoring, not a retry-policy override.
RETRYABLE_FAILURE_CATEGORIES: frozenset[FailureCategory] = frozenset(
    {
        FailureCategory.TIMEOUT,
        FailureCategory.RATE_LIMITED,
        FailureCategory.PROVIDER_ERROR,
        FailureCategory.NETWORK_ERROR,
        FailureCategory.RESOURCE_EXHAUSTED,
        FailureCategory.UNKNOWN,
    }
)

_LEGACY_ERROR_TYPE_MAP: dict[str, FailureCategory] = {
    "AGENT_UNAVAILABLE": FailureCategory.PROVIDER_ERROR,
    "AGENT_CONFIGURATION_ERROR": FailureCategory.VALIDATION_FAILURE,
    "AGENT_TIMEOUT": FailureCategory.TIMEOUT,
    "AGENT_PROCESS_ERROR": FailureCategory.PROVIDER_ERROR,
    "AGENT_OUTPUT_ERROR": FailureCategory.PROVIDER_ERROR,
    "AGENT_AUTHENTICATION_ERROR": FailureCategory.AUTHENTICATION_FAILURE,
    "AGENT_USAGE_LIMIT_ERROR": FailureCategory.RATE_LIMITED,
    "AGENT_PERMISSION_ERROR": FailureCategory.AUTHENTICATION_FAILURE,
    "CIRCUIT_BREAKER_OPEN": FailureCategory.CIRCUIT_OPEN,
    "AGENT_EXECUTOR_NOT_REGISTERED": FailureCategory.INTERNAL_ERROR,
    "INVALID_EXECUTOR_OUTPUT": FailureCategory.VALIDATION_FAILURE,
    "UNEXPECTED_ERROR": FailureCategory.INTERNAL_ERROR,
    "STEP_EXECUTION_FAILED": FailureCategory.UNKNOWN,
}


def classify_legacy_error_type(error_type: str) -> FailureCategory:
    """Map an existing `StepExecutionError.error_type` string to a `FailureCategory`.

    Unrecognized error types map to `FailureCategory.UNKNOWN` rather than
    raising, since new adapter error codes must not break routing/passport
    evidence collection.
    """
    return _LEGACY_ERROR_TYPE_MAP.get(error_type, FailureCategory.UNKNOWN)
