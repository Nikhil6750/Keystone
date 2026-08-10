"""`NemotronManagerModel`: the Stage 8B production `ManagerModel`
implementation for NVIDIA Nemotron 3 Ultra's OpenAI-compatible
`/v1/chat/completions` surface.

```
ManagerRequest                              (Stage 8A, unmodified)
  -> build_chat_messages / build_request_body   (serialization.py)
  -> NemotronTransport.post()                   (transport.py)
  -> status-code interpretation                 (this module)
  -> parse_chat_completion_to_manager_response  (parser.py)
  -> ManagerResponse                          (Stage 8A, unmodified)
```

`ManagerProposalValidator` and everything after it (Stage 8A's
`ManagerOrchestrator`) is untouched by this module -- `propose()` returns a
structurally valid `ManagerResponse` or raises a typed
`app.engine.manager.errors.ManagerError` subclass; Stage 8A decides what
happens next either way.

**Provider/network error mapping (Stage 8B rule 10).** Stage 8A's
`ManagerModel` protocol only allows four failure shapes
(`ManagerUnavailableError`, `ManagerTimeoutError`, `ManagerInvalidResponseError`,
and -- not raised by an implementation -- `ManagerProposalRejectedError`).
Every provider/network condition this adapter can observe is mapped onto
one of the first three:

| Condition | Mapped to |
| --- | --- |
| Connection failure / other transport error | `ManagerUnavailableError` |
| Client-side timeout | `ManagerTimeoutError` |
| HTTP 408 | `ManagerTimeoutError` |
| HTTP 401 / 403 | `ManagerUnavailableError` ("authentication failed") |
| HTTP 429 | `ManagerUnavailableError` ("rate limited") |
| HTTP 400 | `ManagerUnavailableError` ("request rejected") |
| HTTP 404 | `ManagerUnavailableError` ("model or endpoint not found") |
| HTTP 500/502/503/504 | `ManagerUnavailableError` ("server error") |
| any other non-2xx status | `ManagerUnavailableError` ("unexpected status") |
| oversized response body | `ManagerInvalidResponseError` |
| empty / non-string / missing content | `ManagerInvalidResponseError` |
| unexpected `tool_calls` | `ManagerInvalidResponseError` |
| malformed/non-fenced-extractable JSON | `ManagerInvalidResponseError` |
| schema-invalid JSON (fails `ManagerResponse`) | `ManagerInvalidResponseError` |
| any other unexpected exception | `ManagerUnavailableError` (safety net) |

No mapped exception message ever includes the `Authorization` header, the
resolved API key, or raw provider response body content -- see
`errors.py`'s module docstring for the sanitization discipline this table
depends on.

**No retry loop (Stage 8B rule 11).** `propose()` calls the transport
exactly once. Stage 8A's `ManagerOrchestrator` already wraps the whole call
in one bounded `asyncio.wait_for`; adding a retry layer here could exceed
that budget and is deliberately not implemented.
"""

import contextlib
import json
from importlib import metadata

from app.engine.manager.errors import (
    ManagerError,
    ManagerInvalidResponseError,
    ManagerTimeoutError,
    ManagerUnavailableError,
)
from app.engine.manager.models import ManagerRequest, ManagerResponse
from app.integrations.nemotron.config import NemotronConfig
from app.integrations.nemotron.errors import NemotronResponseError, NemotronTransportError
from app.integrations.nemotron.parser import parse_chat_completion_to_manager_response
from app.integrations.nemotron.serialization import build_chat_messages, build_request_body
from app.integrations.nemotron.transport import (
    HttpxNemotronTransport,
    NemotronTransport,
    TransportRequest,
)

_AUTH_STATUS_CODES = frozenset({401, 403})
_SERVER_ERROR_STATUS_CODES = frozenset({500, 502, 503, 504})


def _build_user_agent(config: NemotronConfig) -> str:
    """`<product>/<installed-version>` when the installed package version
    can be resolved, else just `<product>` -- never a fabricated version
    number (Stage 8B rule 14)."""
    version = None
    with contextlib.suppress(metadata.PackageNotFoundError):
        version = metadata.version("keystone-backend")
    return f"{config.user_agent_product}/{version}" if version else config.user_agent_product


def _build_headers(config: NemotronConfig) -> dict[str, str]:
    """Never logged, never included in any raised exception. The
    `Authorization` header is present only when `resolve_api_key()` finds a
    non-empty value -- a self-hosted deployment with no configured
    credential simply sends no `Authorization` header at all."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": _build_user_agent(config),
    }
    api_key = config.resolve_api_key()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _map_status_error(status_code: int) -> ManagerUnavailableError | ManagerTimeoutError:
    if status_code == 408:
        return ManagerTimeoutError(f"nemotron request timed out (HTTP {status_code})")
    if status_code in _AUTH_STATUS_CODES:
        return ManagerUnavailableError(f"nemotron authentication failed (HTTP {status_code})")
    if status_code == 429:
        return ManagerUnavailableError(f"nemotron rate limited (HTTP {status_code})")
    if status_code == 400:
        return ManagerUnavailableError(f"nemotron rejected the request (HTTP {status_code})")
    if status_code == 404:
        return ManagerUnavailableError(
            f"nemotron model or endpoint not found (HTTP {status_code})"
        )
    if status_code in _SERVER_ERROR_STATUS_CODES:
        return ManagerUnavailableError(f"nemotron server error (HTTP {status_code})")
    return ManagerUnavailableError(f"nemotron returned an unexpected status (HTTP {status_code})")


class NemotronManagerModel:
    """Implements Stage 8A's `ManagerModel` Protocol
    (`app.engine.manager.protocol`) against NVIDIA Nemotron 3 Ultra's
    OpenAI-compatible Chat Completions surface. No changes to that
    protocol; see module docstring for the exact request/response
    pipeline and error-mapping table.
    """

    def __init__(
        self, *, config: NemotronConfig | None = None, transport: NemotronTransport | None = None
    ) -> None:
        self._config = config or NemotronConfig()
        self._transport = transport

    def identifier(self) -> str:
        """A short, safe identifier: the configured model name only --
        never a credential, session detail, or prompt."""
        return f"nemotron:{self._config.model}"

    def _resolve_transport(self) -> NemotronTransport:
        if self._transport is not None:
            return self._transport
        try:
            return HttpxNemotronTransport()
        except NemotronTransportError as exc:
            raise ManagerUnavailableError(str(exc)) from exc

    async def propose(self, request: ManagerRequest) -> ManagerResponse:
        """See module docstring for the full pipeline and error-mapping
        table. Guarantees only a typed `ManagerError` subclass ever
        escapes -- any genuinely unexpected exception is caught by the
        last-resort safety net below and re-raised as
        `ManagerUnavailableError`, never a bare/opaque exception."""
        try:
            return await self._propose(request)
        except ManagerError:
            raise
        except Exception as exc:  # last-resort safety net -- see docstring above
            raise ManagerUnavailableError(
                f"unexpected nemotron adapter failure ({type(exc).__name__})"
            ) from exc

    async def _propose(self, request: ManagerRequest) -> ManagerResponse:
        transport = self._resolve_transport()
        headers = _build_headers(self._config)
        messages = build_chat_messages(request)
        body = build_request_body(self._config, messages)
        transport_request = TransportRequest(
            url=self._config.chat_completions_url,
            headers=headers,
            json_body=body,
            timeout_seconds=self._config.timeout_seconds,
            max_response_body_bytes=self._config.max_response_body_bytes,
        )

        try:
            response = await transport.post(transport_request)
        except NemotronTransportError as exc:
            if exc.is_timeout:
                raise ManagerTimeoutError(str(exc)) from exc
            raise ManagerUnavailableError(str(exc)) from exc
        except NemotronResponseError as exc:
            # Raised by the transport itself only for an oversized body.
            raise ManagerInvalidResponseError(str(exc)) from exc

        if not 200 <= response.status_code < 300:
            raise _map_status_error(response.status_code)

        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ManagerInvalidResponseError(
                "provider response body is not valid UTF-8 JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise ManagerInvalidResponseError("provider response body is not a JSON object")

        try:
            return parse_chat_completion_to_manager_response(payload)
        except NemotronResponseError as exc:
            raise ManagerInvalidResponseError(str(exc)) from exc
        # `ManagerInvalidResponseError` raised directly by
        # `parse_manager_response` (a schema-invalid `ManagerResponse`)
        # propagates unchanged -- it is already the correct Stage 8A type.


__all__ = ["NemotronManagerModel"]
