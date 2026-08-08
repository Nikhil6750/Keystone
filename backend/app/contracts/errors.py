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


# --- Canonical retry-policy decision -----------------------------------------
#
# `RETRYABLE_FAILURE_CATEGORIES` (above) is a *broad, observability-oriented*
# bucketing: it groups codes for routing/passport evidence and is
# deliberately coarse. It is NOT authoritative for "should this be retried" —
# two of its members disagree with the live engine's deliberate, documented
# per-adapter-exception `retryable` flags (`app.adapters.exceptions`):
#
# - AGENT_UNAVAILABLE buckets into PROVIDER_ERROR (broadly retryable), but the
#   live engine deliberately treats it as non-retryable: the executable
#   itself could not be resolved, and retrying will not change that.
# - AGENT_USAGE_LIMIT_ERROR buckets into RATE_LIMITED (broadly retryable),
#   but the live engine deliberately treats it as non-retryable: there is no
#   retry-after-aware scheduling yet, so an immediate retry would just fail
#   identically (see `AgentUsageLimitError`'s own docstring).
#
# `is_legacy_error_type_retryable` is the single canonical source of truth
# for the actual retry decision, matching the live adapters' flags exactly.
# The live synchronous `WorkflowEngine` does not need to call this — it
# already reads `StepExecutionError.retryable` straight from the raised
# exception, which is where these semantics are defined — but any new
# consumer (e.g. the async `RetryingStepRunner`) that only has an
# `error_type` string to go on, not the original exception object, must use
# this function rather than `classify_legacy_error_type(...) in
# RETRYABLE_FAILURE_CATEGORIES`, to avoid silently disagreeing with the live
# engine's deliberate behavior.
_LEGACY_ERROR_TYPE_RETRYABLE: dict[str, bool] = {
    "AGENT_UNAVAILABLE": False,
    "AGENT_CONFIGURATION_ERROR": False,
    "AGENT_TIMEOUT": True,
    "AGENT_PROCESS_ERROR": True,
    "AGENT_OUTPUT_ERROR": True,
    "AGENT_AUTHENTICATION_ERROR": False,
    "AGENT_USAGE_LIMIT_ERROR": False,
    "AGENT_PERMISSION_ERROR": False,
    "CIRCUIT_BREAKER_OPEN": False,
    "AGENT_EXECUTOR_NOT_REGISTERED": False,
    "INVALID_EXECUTOR_OUTPUT": False,
    "UNEXPECTED_ERROR": False,
}

# Unrecognized error types default to retryable, matching this codebase's
# existing "retryable by default when uncertain" precedent for genuinely
# unclassified failures (see `AgentOutputError`'s own default and
# `STEP_EXECUTION_FAILED`'s `FailureCategory.UNKNOWN` bucketing above).
_DEFAULT_RETRYABLE_WHEN_UNKNOWN = True


def is_legacy_error_type_retryable(error_type: str) -> bool:
    """The canonical, single-source-of-truth retry decision for a legacy
    `error_type` string — authoritative for both the live engine's adapter
    exceptions and the additive async retry layer. See the module-level note
    above for why this is not simply `classify_legacy_error_type(...) in
    RETRYABLE_FAILURE_CATEGORIES`.
    """
    return _LEGACY_ERROR_TYPE_RETRYABLE.get(error_type, _DEFAULT_RETRYABLE_WHEN_UNKNOWN)
