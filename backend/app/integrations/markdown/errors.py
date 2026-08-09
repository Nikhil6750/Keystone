"""Typed exception hierarchy for the generic Markdown knowledge integration.

Mirrors the "never silently repair, always fail loudly on a malformed
input" discipline used by `app.engine.knowledge.errors`. These errors are
raised only for a genuine configuration or safety problem -- a single
unreadable or empty note is never allowed to raise out of a scan/sync; it
is instead reported as a typed failure entry (see `app.integrations.
markdown.models.NoteFailure`) so the rest of the source tree keeps
syncing.
"""


class MarkdownIntegrationError(Exception):
    """Base class for typed Stage 6B Markdown-integration errors."""


class MarkdownSourceConfigError(MarkdownIntegrationError):
    """Raised for an invalid `MarkdownSourceConfig`: a missing/non-directory
    root, or a blank `source_id`."""


class PathSafetyError(MarkdownIntegrationError):
    """Raised when a path would resolve outside the configured root --
    `../` traversal, an absolute out-of-root path, or a symlink/junction
    escape. Never includes the offending absolute host path in its message,
    only the root-relative identifier that was rejected."""


class NoteParseError(MarkdownIntegrationError):
    """Raised internally while parsing one note; always caught by the
    scanner/sync layer and converted into a `NoteFailure` entry -- never
    allowed to propagate out of `sync_source` or `MarkdownKnowledgeSource.
    list_documents`."""


__all__ = [
    "MarkdownIntegrationError",
    "MarkdownSourceConfigError",
    "NoteParseError",
    "PathSafetyError",
]
