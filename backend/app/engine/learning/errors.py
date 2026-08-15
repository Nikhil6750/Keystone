"""Typed exception hierarchy for the Stage 5A learning core.

Raised only for a caller/data-shape problem (a malformed `LearningEvent`) --
never for a normal execution/verification *outcome*, however unfavorable
(a failed execution, a failed verification, a cancellation are all valid,
well-formed events, not errors). Mirrors the "never silently repair, always
fail loudly on a malformed input" discipline already used by Stage 4C's
`ExplainabilityDataError` and Stage 4E's `VerificationEngineError`.
"""


class LearningEngineError(ValueError):
    """Base class for typed Stage 5A learning-core errors."""


class MalformedLearningEventError(LearningEngineError):
    """Raised when a `LearningEvent`'s fields are internally inconsistent or
    unsafe: a blank identifier, a negative `attempt_number`, non-finite or
    negative `duration_ms`/`cost_usd`, an `execution_status`/`failure_category`
    pairing that doesn't match `AgentExecutionResult`'s own invariant, or a
    `repository_id` that looks like an absolute filesystem path."""


__all__ = ["LearningEngineError", "MalformedLearningEventError"]
