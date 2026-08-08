"""Typed exception hierarchy for the Stage 6A knowledge engine.

Raised only for a caller/data-shape problem (a malformed or unsafe
`KnowledgeDocument`/`KnowledgeChunk`/request) -- never for a normal "no
results" outcome, which is a valid, empty result list, not an error.
Mirrors the "never silently repair, always fail loudly on a malformed
input" discipline already used by Stage 4C's `ExplainabilityDataError`,
Stage 4E's `VerificationEngineError`, and Stage 5's `LearningEngineError`.
"""


class KnowledgeEngineError(ValueError):
    """Base class for typed Stage 6A knowledge-engine errors."""


class MalformedKnowledgeDataError(KnowledgeEngineError):
    """Raised when a `KnowledgeDocument`/`KnowledgeChunk`/search request's
    fields are invalid: a blank identifier, empty content, a malformed
    chunk/document relationship, or an invalid budget/limit."""


class UnsafeKnowledgeDataError(KnowledgeEngineError):
    """Raised when knowledge metadata is unsafe: a reasoning-shaped key, a
    credential-shaped key, or a value that looks like an absolute local
    filesystem path."""


__all__ = ["KnowledgeEngineError", "MalformedKnowledgeDataError", "UnsafeKnowledgeDataError"]
