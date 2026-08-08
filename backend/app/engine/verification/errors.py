"""Typed exception hierarchy for the Stage 4E verification/recovery engine.

Every error here is raised for a caller/config-shape problem (malformed
`ExpectedOutcome.criteria`, an evaluator type with no registered
implementation, evidence containing a reserved reasoning-shaped key, or an
unconfigured command-execution boundary) -- never for "the check failed
objectively," which is a normal `VerificationStatus.FAILED`/`INCONCLUSIVE`
outcome, not an exception. Mirrors the "never silently repair, always fail
loudly on a malformed input" discipline used by Stage 4C's
`ExplainabilityDataError`.
"""

from typing import Any


class VerificationEngineError(ValueError):
    """Base class for typed Stage 4E verification/recovery errors."""


class MalformedExpectedOutcomeError(VerificationEngineError):
    """Raised when `ExpectedOutcome.criteria` is missing a required key or
    has the wrong shape for its `evaluator_type` -- a caller/config bug,
    never silently guessed at or defaulted."""


class UnsupportedEvaluatorError(VerificationEngineError):
    """Raised when `evaluator_type` has no registered evaluator
    implementation. Every current `BenchmarkEvaluatorType` member is
    registered (see `registry.py`); this exists for forward-compatibility
    if the shared enum ever grows a member before an evaluator is added."""

    def __init__(self, evaluator_type: Any) -> None:
        self.evaluator_type = evaluator_type
        super().__init__(f"no evaluator is registered for evaluator_type={evaluator_type!r}")


class UnsafeEvidenceError(VerificationEngineError):
    """Raised when observed evidence contains a reserved reasoning-shaped
    key -- Stage 4E explains only Keystone's own observable evidence, never
    a model's internal reasoning."""


class CommandExecutionNotConfiguredError(VerificationEngineError):
    """Raised by `NullCommandExecutor`, the default `CommandExecutor` that
    always refuses. Guarantees that no Stage 4E evaluator can cause a
    process to run unless a caller explicitly injects a real (and, on their
    own responsibility, sandboxed) executor."""

    def __init__(self, spec: Any) -> None:
        self.spec = spec
        super().__init__(
            "no CommandExecutor was configured; Stage 4E never executes a process by default"
        )


__all__ = [
    "CommandExecutionNotConfiguredError",
    "MalformedExpectedOutcomeError",
    "UnsafeEvidenceError",
    "UnsupportedEvaluatorError",
    "VerificationEngineError",
]
