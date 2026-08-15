"""Exceptions raised while building or running a workflow graph."""


class GraphValidationError(ValueError):
    """Base class for structural problems in a workflow graph."""


class CycleDetectedError(GraphValidationError):
    """Raised when a workflow's `depends_on` edges form a cycle."""

    def __init__(self, cycle: list[str]) -> None:
        self.cycle = cycle
        super().__init__(f"workflow graph contains a cycle: {' -> '.join(cycle)}")


class StepRunnerError(Exception):
    """Raised by a `StepRunner` for an expected, handleable step failure.

    Mirrors `app.engine.executor.StepExecutionError`'s shape deliberately,
    but is defined independently so this package has no import dependency on
    the live sequential engine.
    """

    def __init__(self, message: str, *, error_type: str = "STEP_EXECUTION_FAILED") -> None:
        super().__init__(message)
        self.error_type = error_type
