"""Typed exception hierarchy for Stage 7.5 Self-Learning RAG Core."""


class AdaptiveRetrievalError(ValueError):
    """Base class for typed Stage 7.5 adaptive-retrieval errors."""


class MalformedRetrievalObservationError(AdaptiveRetrievalError):
    """Raised when a `RetrievalObservation`'s fields are invalid: a blank
    identifier, mismatched parallel-tuple lengths, a duplicate retrieved
    chunk id, or a `selected_chunk_ids` entry that was never actually
    retrieved (base-retrieval eligibility must never be bypassed)."""


class MalformedRetrievalFeedbackError(AdaptiveRetrievalError):
    """Raised when a `RetrievalFeedback`'s fields are invalid: a blank
    identifier, mismatched parallel-tuple lengths, or an
    `evidence_source`/`campaign_id` pairing that doesn't match Stage 7B's
    own invariant (`campaign_id` required for `BENCHMARK`, forbidden for
    `PRODUCTION`)."""


class RetrievalFeedbackConflictError(AdaptiveRetrievalError):
    """Raised when two `RetrievalFeedback` records share the same
    `feedback_id` but carry different observable content -- a genuine data
    conflict, never silently resolved by picking one."""


class MalformedAdaptiveRetrievalPolicyError(AdaptiveRetrievalError):
    """Raised when an `AdaptiveRetrievalPolicy`'s fields are invalid: a
    negative bound, or a non-positive `minimum_verified_samples`."""


__all__ = [
    "AdaptiveRetrievalError",
    "MalformedAdaptiveRetrievalPolicyError",
    "MalformedRetrievalFeedbackError",
    "MalformedRetrievalObservationError",
    "RetrievalFeedbackConflictError",
]
