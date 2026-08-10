"""`FakeNemotronTransport`: a deterministic `NemotronTransport` test double.

No network I/O, no `httpx` dependency at all. Mirrors
`app.engine.manager.fake.FakeManagerModel`'s shape exactly: configure
`response` or `exception`, call `post`, inspect `calls` afterward.
"""

from dataclasses import dataclass, field

from app.integrations.nemotron.errors import NemotronIntegrationError
from app.integrations.nemotron.transport import TransportRequest, TransportResponse


@dataclass
class FakeNemotronTransport:
    """A controllable `NemotronTransport` for tests.

    `response` and `exception` are mutually exclusive per call: if
    `exception` is set, `post` raises it; otherwise, if `response` is set,
    `post` returns it; if neither is set, `post` raises `AssertionError` --
    every real test configures one of the two before calling `propose()`.
    """

    response: TransportResponse | None = None
    exception: NemotronIntegrationError | None = None
    calls: list[TransportRequest] = field(default_factory=list)

    async def post(self, request: TransportRequest) -> TransportResponse:
        self.calls.append(request)
        if self.exception is not None:
            raise self.exception
        if self.response is not None:
            return self.response
        raise AssertionError(
            "FakeNemotronTransport has no configured response or exception -- "
            "set one of them before calling propose()"
        )


__all__ = ["FakeNemotronTransport"]
