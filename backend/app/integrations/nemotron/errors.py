"""Typed exception hierarchy internal to the Stage 8B Nemotron integration.

These are deliberately *not* `app.engine.manager.errors.ManagerError`
subclasses -- they describe failure at a lower layer (HTTP transport,
response-shape parsing) than the `ManagerModel` protocol boundary.
`app.integrations.nemotron.adapter.NemotronManagerModel.propose()` is the
single place that catches these and maps them into the correct
`ManagerError` subclass before they can cross the Stage 8A boundary (see
`adapter.py`'s module docstring for the exact mapping table) -- mirroring
the layering `app.adapters.exceptions.AgentAdapterError` uses relative to
`app.engine.executor.StepExecutionError`.

Every message constructed for these errors is built from fixed strings and
safe, non-secret values (an HTTP status code, an exception *type* name)
only -- never `str(exc)` on a caught transport exception (which could
incidentally echo request details) and never raw response body content
(which is untrusted provider output and must not be echoed verbatim into
logs/exceptions).
"""


class NemotronIntegrationError(Exception):
    """Base class for typed Stage 8B Nemotron-integration errors."""


class NemotronTransportError(NemotronIntegrationError):
    """A transport-level failure reaching the configured Nemotron endpoint
    at all: connection failure, TLS failure, or a client-side timeout.
    Never raised for a non-2xx HTTP status that a response body -- however
    unusable -- was actually received for; see `NemotronResponseError` and
    `TransportResponse.status_code` for that case."""

    def __init__(self, message: str, *, is_timeout: bool = False) -> None:
        self.is_timeout = is_timeout
        super().__init__(message)


class NemotronResponseError(NemotronIntegrationError):
    """The transport call completed, but the response body could not be
    turned into a usable `ManagerResponse`: it exceeded the configured size
    bound, was missing `choices`, carried empty/non-string `content`,
    carried unexpected `tool_calls`, or failed to decode as JSON (including
    after the one narrow fenced-code-block fallback -- see `parser.py`)."""


__all__ = [
    "NemotronIntegrationError",
    "NemotronResponseError",
    "NemotronTransportError",
]
