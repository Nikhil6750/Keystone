"""`NemotronTransport`: the narrow HTTP boundary between
`NemotronManagerModel` (`adapter.py`) and the actual network call.

The adapter never touches `httpx` (or any HTTP client) directly -- it only
depends on this module's `NemotronTransport` Protocol, so
`app.integrations.nemotron.adapter` and `app.integrations.nemotron.
serialization`/`parser` stay fully testable with `fake.FakeNemotronTransport`
and have zero coupling to the concrete transport implementation.

**`httpx` is imported lazily**, inside `HttpxNemotronTransport.__init__`,
not at module import time. `httpx` is currently declared only in this
repository's `dev`/`dependency-groups` scope (see
`docs/stage8/nemotron-integration-spike.md` section 10 and this stage's
final report) -- promoting it to a main runtime dependency is a
`pyproject.toml` change explicitly out of scope for this stage. Deferring
the import means:

- `app.integrations.nemotron` (including `adapter.py`) stays importable in
  *any* environment, including one where only main dependencies are
  installed.
- Only actually constructing an `HttpxNemotronTransport` requires `httpx`
  to be present; if it is not, construction raises `NemotronTransportError`,
  which `adapter.py` maps to `ManagerUnavailableError` -- the same
  deterministic-fallback path Stage 8A already uses for "manager model is
  unavailable" for any other reason. A stripped-down deployment without
  `httpx` installed simply behaves as if Nemotron were unreachable, rather
  than failing to import at all.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.integrations.nemotron.errors import NemotronResponseError, NemotronTransportError


@dataclass(frozen=True)
class TransportRequest:
    """Everything one POST call needs -- provider-agnostic within "an
    OpenAI-compatible chat completions endpoint", not specific to `httpx`."""

    url: str
    headers: dict[str, str]
    json_body: dict[str, Any]
    timeout_seconds: float
    max_response_body_bytes: int


@dataclass(frozen=True)
class TransportResponse:
    """One completed HTTP exchange, for *any* status code -- `NemotronTransport
    .post()` returns this for every response it actually received; it never
    raises merely because the status code is not 2xx. Status-code
    interpretation is `adapter.py`'s job (Stage 8B rule 4: "adapter
    responsibilities: ... error mapping"), not the transport's."""

    status_code: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)


class NemotronTransport(Protocol):
    """The HTTP transport boundary `NemotronManagerModel` depends on."""

    async def post(self, request: TransportRequest) -> TransportResponse:
        """Perform one bounded POST call.

        Raises `NemotronTransportError` only for a failure that prevented
        receiving *any* HTTP response at all (connection failure, TLS
        failure, client-side timeout) -- `is_timeout=True` for the timeout
        case specifically. Raises `NemotronResponseError` if a response was
        received but its body exceeded `request.max_response_body_bytes`
        before it could be fully read. Otherwise always returns a
        `TransportResponse`, regardless of status code.
        """
        ...


class HttpxNemotronTransport:
    """Production `NemotronTransport` backed by `httpx.AsyncClient`.

    Streams the response body and aborts (raising `NemotronResponseError`)
    as soon as `max_response_body_bytes` is exceeded, rather than buffering
    an unbounded body into memory first and checking its size afterward --
    this is the actual memory-bound guarantee Stage 8B rule 12 asks for,
    not just a post-hoc truncation.
    """

    def __init__(self, *, httpx_transport: Any = None) -> None:
        """`httpx_transport`, if given, is passed straight through to
        `httpx.AsyncClient(transport=...)` -- e.g. an `httpx.MockTransport`
        for fully offline tests that exercise real `httpx` streaming/
        timeout/status-code behavior without any network call. `None` (the
        default) uses `httpx`'s own real network transport."""
        try:
            import httpx
        except ImportError as exc:
            raise NemotronTransportError(
                "httpx is not installed; the Nemotron HTTP transport is unavailable "
                "in this environment"
            ) from exc
        self._httpx = httpx
        self._httpx_transport = httpx_transport

    async def post(self, request: TransportRequest) -> TransportResponse:
        httpx = self._httpx
        try:
            async with (
                httpx.AsyncClient(
                    timeout=request.timeout_seconds, transport=self._httpx_transport
                ) as client,
                client.stream(
                    "POST", request.url, headers=request.headers, json=request.json_body
                ) as response,
            ):
                body = await _read_bounded(response, request.max_response_body_bytes)
                return TransportResponse(
                    status_code=response.status_code, body=body, headers=dict(response.headers)
                )
        except NemotronResponseError:
            raise
        except httpx.TimeoutException as exc:
            raise NemotronTransportError(
                "request to the Nemotron endpoint timed out", is_timeout=True
            ) from exc
        except httpx.HTTPError as exc:
            raise NemotronTransportError(
                f"transport error contacting the Nemotron endpoint ({type(exc).__name__})"
            ) from exc


async def _read_bounded(response: Any, max_bytes: int) -> bytes:
    """Read `response`'s body in chunks via `aiter_bytes()`, aborting with
    `NemotronResponseError` the moment the running total exceeds
    `max_bytes` -- never buffers more than `max_bytes` (plus at most one
    chunk's worth) into memory."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise NemotronResponseError(
                f"Nemotron response body exceeded the maximum allowed size of {max_bytes} bytes"
            )
        chunks.append(chunk)
    return b"".join(chunks)


__all__ = [
    "HttpxNemotronTransport",
    "NemotronTransport",
    "TransportRequest",
    "TransportResponse",
]
