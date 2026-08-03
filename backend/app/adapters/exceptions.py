"""Typed local-CLI-adapter exceptions.

Each is a `StepExecutionError` subclass (see `app.engine.executor`) so the
existing workflow engine catches and persists them without any special
casing, carrying a stable `error_code` and whether the engine should retry.
"""

from app.engine.executor import StepExecutionError


class AgentAdapterError(StepExecutionError):
    """Base class for all local-CLI-adapter errors."""

    def __init__(self, message: str, *, error_code: str, retryable: bool) -> None:
        super().__init__(message, error_type=error_code, retryable=retryable)
        self.error_code = error_code


class AgentUnavailableError(AgentAdapterError):
    """The configured executable could not be resolved. Not retryable."""

    def __init__(self, message: str) -> None:
        super().__init__(message, error_code="AGENT_UNAVAILABLE", retryable=False)


class AgentConfigurationError(AgentAdapterError):
    """The adapter's configuration (profile, prompt) is invalid. Not retryable."""

    def __init__(self, message: str) -> None:
        super().__init__(message, error_code="AGENT_CONFIGURATION_ERROR", retryable=False)


class AgentTimeoutError(AgentAdapterError):
    """The CLI process exceeded its configured timeout. Retryable."""

    def __init__(self, message: str) -> None:
        super().__init__(message, error_code="AGENT_TIMEOUT", retryable=True)


class AgentProcessError(AgentAdapterError):
    """The CLI process exited non-zero or otherwise failed to run. Retryable."""

    def __init__(self, message: str) -> None:
        super().__init__(message, error_code="AGENT_PROCESS_ERROR", retryable=True)


class AgentOutputError(AgentAdapterError):
    """The CLI process's output was empty, malformed, or oversized.

    Retryable by default, since transient truncation or a one-off malformed
    response is often worth one more attempt. A provider-specific parser may
    pass `retryable=False` when the schema violation is clearly deterministic.
    """

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message, error_code="AGENT_OUTPUT_ERROR", retryable=retryable)


class AgentAuthenticationError(AgentAdapterError):
    """The provider CLI is not authenticated (or its session expired). Not
    retryable — requires the operator to run the provider's local login
    command; no automated retry can fix this."""

    def __init__(self, message: str) -> None:
        super().__init__(message, error_code="AGENT_AUTHENTICATION_ERROR", retryable=False)


class AgentUsageLimitError(AgentAdapterError):
    """The provider reported a usage/quota/rate limit. Not retryable by
    default in this prototype — the existing resilience policy has no
    retry-after-aware scheduling, so retrying immediately would just fail
    again identically."""

    def __init__(self, message: str) -> None:
        super().__init__(message, error_code="AGENT_USAGE_LIMIT_ERROR", retryable=False)


class AgentPermissionError(AgentAdapterError):
    """The provider CLI refused to proceed pending a permission/approval only
    a human can grant interactively. Not retryable."""

    def __init__(self, message: str) -> None:
        super().__init__(message, error_code="AGENT_PERMISSION_ERROR", retryable=False)
