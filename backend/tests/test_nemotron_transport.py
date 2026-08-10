"""Tests for `app.integrations.nemotron.transport` and `fake.FakeNemotronTransport`.

`HttpxNemotronTransport` is tested fully offline via `httpx.MockTransport`
(a real `httpx` feature that swaps only the lowest-level network transport,
so these tests exercise real `httpx` streaming/timeout/status-code
behavior without ever touching the network).
"""

import sys

import httpx
import pytest

from app.integrations.nemotron.errors import NemotronResponseError, NemotronTransportError
from app.integrations.nemotron.fake import FakeNemotronTransport
from app.integrations.nemotron.transport import (
    HttpxNemotronTransport,
    TransportRequest,
    TransportResponse,
    _read_bounded,
)


def _request(**overrides: object) -> TransportRequest:
    base: dict[str, object] = {
        "url": "https://example.test/v1/chat/completions",
        "headers": {},
        "json_body": {"model": "x", "messages": []},
        "timeout_seconds": 5.0,
        "max_response_body_bytes": 1000,
    }
    base.update(overrides)
    return TransportRequest(**base)  # type: ignore[arg-type]


class _FakeAsyncResponse:
    """A minimal stand-in for `httpx.Response` exposing only what
    `_read_bounded` uses (`aiter_bytes`), so the bounded-read logic is
    testable in complete isolation from `httpx`."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


# --- _read_bounded ------------------------------------------------------


async def test_read_bounded_returns_full_body_within_limit() -> None:
    response = _FakeAsyncResponse([b"hello ", b"world"])
    body = await _read_bounded(response, max_bytes=100)
    assert body == b"hello world"


async def test_read_bounded_raises_when_exceeding_limit() -> None:
    response = _FakeAsyncResponse([b"x" * 60, b"y" * 60])
    with pytest.raises(NemotronResponseError, match="exceeded the maximum allowed size"):
        await _read_bounded(response, max_bytes=100)


async def test_read_bounded_exact_limit_is_allowed() -> None:
    response = _FakeAsyncResponse([b"x" * 100])
    body = await _read_bounded(response, max_bytes=100)
    assert body == b"x" * 100


# --- HttpxNemotronTransport (offline, via httpx.MockTransport) ----------


async def test_httpx_transport_correct_endpoint_and_headers_and_body() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = request.read()
        return httpx.Response(200, json={"choices": []})

    transport = HttpxNemotronTransport(httpx_transport=httpx.MockTransport(handler))
    await transport.post(
        _request(
            url="https://integrate.api.nvidia.com/v1/chat/completions",
            headers={"Authorization": "Bearer secret-token", "X-Test": "yes"},
            json_body={"model": "nvidia/nemotron-3-ultra-550b-a55b"},
        )
    )
    assert captured["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert captured["headers"]["x-test"] == "yes"
    assert b"nemotron-3-ultra" in captured["body"]  # type: ignore[operator]


async def test_httpx_transport_returns_response_for_non_2xx_status() -> None:
    """The transport itself never raises merely for a non-2xx status --
    that is the adapter's job (Stage 8B rule 4)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    transport = HttpxNemotronTransport(httpx_transport=httpx.MockTransport(handler))
    response = await transport.post(_request())
    assert isinstance(response, TransportResponse)
    assert response.status_code == 401


async def test_httpx_transport_enforces_response_size_bound() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 5000)

    transport = HttpxNemotronTransport(httpx_transport=httpx.MockTransport(handler))
    with pytest.raises(NemotronResponseError):
        await transport.post(_request(max_response_body_bytes=100))


async def test_httpx_transport_maps_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("simulated timeout")

    transport = HttpxNemotronTransport(httpx_transport=httpx.MockTransport(handler))
    with pytest.raises(NemotronTransportError) as excinfo:
        await transport.post(_request())
    assert excinfo.value.is_timeout is True


async def test_httpx_transport_maps_connection_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated connection failure")

    transport = HttpxNemotronTransport(httpx_transport=httpx.MockTransport(handler))
    with pytest.raises(NemotronTransportError) as excinfo:
        await transport.post(_request())
    assert excinfo.value.is_timeout is False


def test_httpx_transport_construction_fails_safely_when_httpx_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "httpx", None)
    with pytest.raises(NemotronTransportError, match="httpx is not installed"):
        HttpxNemotronTransport()


# --- FakeNemotronTransport ------------------------------------------------


async def test_fake_transport_returns_configured_response() -> None:
    response = TransportResponse(status_code=200, body=b"{}")
    fake = FakeNemotronTransport(response=response)
    result = await fake.post(_request())
    assert result is response


async def test_fake_transport_raises_configured_exception() -> None:
    fake = FakeNemotronTransport(exception=NemotronTransportError("simulated"))
    with pytest.raises(NemotronTransportError):
        await fake.post(_request())


async def test_fake_transport_raises_when_unconfigured() -> None:
    fake = FakeNemotronTransport()
    with pytest.raises(AssertionError):
        await fake.post(_request())


async def test_fake_transport_captures_calls() -> None:
    response = TransportResponse(status_code=200, body=b"{}")
    fake = FakeNemotronTransport(response=response)
    request_a = _request(url="https://a.test")
    request_b = _request(url="https://b.test")
    await fake.post(request_a)
    await fake.post(request_b)
    assert fake.calls == [request_a, request_b]


async def test_fake_transport_never_performs_network_io(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("FakeNemotronTransport must never open a socket")

    monkeypatch.setattr(socket, "socket", _forbidden)
    response = TransportResponse(status_code=200, body=b"{}")
    fake = FakeNemotronTransport(response=response)
    result = await fake.post(_request())
    assert result is response
