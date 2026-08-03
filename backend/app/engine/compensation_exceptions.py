"""Typed compensation exceptions, each with a stable error code and retryability."""

from app.models.enums import WorkflowStatus


class CompensationError(Exception):
    """Base class for all compensation-layer errors."""

    def __init__(self, message: str, *, error_code: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable


class CompensationHandlerNotRegisteredError(CompensationError):
    """No compensation handler is registered for the requested handler name. Not retryable."""

    def __init__(self, handler_name: str) -> None:
        self.handler_name = handler_name
        super().__init__(
            f"no compensation handler registered for '{handler_name}'",
            error_code="COMPENSATION_HANDLER_NOT_REGISTERED",
            retryable=False,
        )


class CompensationExecutionError(CompensationError):
    """A compensation handler ran but failed, or raised an unexpected error. Not retryable."""

    def __init__(self, message: str) -> None:
        super().__init__(message, error_code="COMPENSATION_EXECUTION_FAILED", retryable=False)


class CompensationAlreadyCompletedError(CompensationError):
    """The workflow has already been compensated; compensation must not run twice."""

    def __init__(self, workflow_id: str) -> None:
        self.workflow_id = workflow_id
        super().__init__(
            f"workflow '{workflow_id}' has already been compensated",
            error_code="COMPENSATION_ALREADY_COMPLETED",
            retryable=False,
        )


class InvalidCompensationStateError(CompensationError):
    """Compensation was attempted from a workflow status other than `FAILED`."""

    def __init__(self, workflow_id: str, current_status: WorkflowStatus) -> None:
        self.workflow_id = workflow_id
        self.current_status = current_status
        super().__init__(
            f"workflow '{workflow_id}' cannot begin compensation from status "
            f"'{current_status.value}'",
            error_code="INVALID_COMPENSATION_STATE",
            retryable=False,
        )
