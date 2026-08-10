"""Typed exception hierarchy for the Stage 8C.1 end-to-end orchestration
service.

Mirrors the discipline used throughout this codebase (`app.engine.manager.
errors`, `app.engine.verification.errors`, `app.engine.learning.errors`):
raised only for a genuine caller/input-shape problem or a truly
unexpected infrastructure failure -- never for an expected, deterministic
business outcome (no eligible route, verification failure, recovery
exhaustion, cancellation). Those are represented as typed fields on
`OrchestrationResult` (`models.py`), exactly like `ManagerOrchestrator`
never raises for "manager unavailable" -- it returns a result describing
the fallback that happened. This module's errors are for the small
remaining set of cases where returning a result would be misleading rather
than informative: the request itself was unusable, or persistence broke in
a way no result field could safely describe.
"""


class OrchestrationError(Exception):
    """Base class for typed Stage 8C.1 orchestration-service errors."""


class InvalidOrchestrationRequestError(OrchestrationError):
    """Raised for an `OrchestrationRequest` (or service configuration) that
    cannot be processed at all -- e.g. no candidate agent types configured
    anywhere reachable, or a request referencing a repository/task shape
    the wired-in subsystems cannot accept. Never raised for "no eligible
    route was found for this otherwise-valid request" (see
    `OrchestrationOutcome.NO_ELIGIBLE_ROUTE` in `models.py`) -- that is an
    outcome, not an input error."""


class OrchestrationPersistenceError(OrchestrationError):
    """Wraps a lower-level persistence failure (a database error, a
    conflicting replay) behind a safe, sanitized message -- never leaks a
    raw SQLAlchemy exception, connection string, or query text to a public
    result model. The original exception is always chained via `from` for
    server-side diagnostics, never displayed to a caller."""


class OrchestrationExecutionNotFoundError(OrchestrationError):
    """Stage 8C.2: raised when a referenced execution ID does not exist in
    the configured `OrchestrationExecutionStore`. Mirrors
    `app.engine.exceptions.WorkflowNotFoundError`'s exact shape."""

    def __init__(self, execution_id: str) -> None:
        self.execution_id = execution_id
        super().__init__(f"orchestration execution '{execution_id}' not found")


__all__ = [
    "InvalidOrchestrationRequestError",
    "OrchestrationError",
    "OrchestrationExecutionNotFoundError",
    "OrchestrationPersistenceError",
]
