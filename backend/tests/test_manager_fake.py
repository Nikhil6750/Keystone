"""Tests for `app.engine.manager.fake.FakeManagerModel`: the deterministic
test double that lets Stage 8A be fully tested without Nemotron."""

import pytest

from app.engine.manager.errors import ManagerTimeoutError, ManagerUnavailableError
from app.engine.manager.fake import FakeManagerModel
from app.engine.manager.models import ManagerRequest, ManagerResponse


def _request(request_id: str = "req-1") -> ManagerRequest:
    return ManagerRequest(request_id=request_id, goal="goal")


async def test_returns_configured_response() -> None:
    response = ManagerResponse(request_id="req-1")
    fake = FakeManagerModel(response=response)
    result = await fake.propose(_request())
    assert result is response


async def test_raises_configured_exception() -> None:
    fake = FakeManagerModel(exception=ManagerTimeoutError("simulated timeout"))
    with pytest.raises(ManagerTimeoutError):
        await fake.propose(_request())


async def test_raises_manager_unavailable_when_unconfigured() -> None:
    fake = FakeManagerModel()
    with pytest.raises(ManagerUnavailableError):
        await fake.propose(_request())


async def test_captures_every_call() -> None:
    response = ManagerResponse(request_id="req-1")
    fake = FakeManagerModel(response=response)
    first = _request("req-1")
    second = _request("req-1")
    await fake.propose(first)
    await fake.propose(second)
    assert fake.calls == [first, second]


def test_identifier_is_safe_and_stable() -> None:
    fake = FakeManagerModel(provider_identifier="fake-manager-v1")
    assert fake.identifier() == "fake-manager-v1"
    for forbidden in ("key", "token", "secret", "password", "credential"):
        assert forbidden not in fake.identifier().lower()


async def test_no_external_api_or_network_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """`FakeManagerModel.propose` must never attempt any network I/O --
    poison `socket.socket` and confirm the fake still works."""
    import socket

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("FakeManagerModel must never open a socket")

    monkeypatch.setattr(socket, "socket", _forbidden)
    response = ManagerResponse(request_id="req-1")
    fake = FakeManagerModel(response=response)
    result = await fake.propose(_request())
    assert result is response
