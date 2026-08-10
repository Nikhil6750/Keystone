"""`FakeManagerModel`: a deterministic `ManagerModel` test double.

No external API, no network I/O, no NVIDIA/OpenAI/Anthropic SDK. Configure
exactly one of `response`/`exception` and call `propose` -- every received
`ManagerRequest` is captured in `calls` for assertions. This is what lets
Stage 8A be fully tested without Nemotron (Stage 8B).
"""

from dataclasses import dataclass, field

from app.engine.manager.errors import ManagerError, ManagerUnavailableError
from app.engine.manager.models import ManagerRequest, ManagerResponse


@dataclass
class FakeManagerModel:
    """A controllable `ManagerModel` for tests.

    `response` and `exception` are mutually exclusive per call: if
    `exception` is set, `propose` raises it; otherwise, if `response` is
    set, `propose` returns it; if neither is set, `propose` raises
    `ManagerUnavailableError` (a safe, typed default rather than returning
    `None` or crashing with an unrelated error).
    """

    response: ManagerResponse | None = None
    exception: ManagerError | None = None
    provider_identifier: str = "fake-manager"
    calls: list[ManagerRequest] = field(default_factory=list)

    def identifier(self) -> str:
        return self.provider_identifier

    async def propose(self, request: ManagerRequest) -> ManagerResponse:
        self.calls.append(request)
        if self.exception is not None:
            raise self.exception
        if self.response is not None:
            return self.response
        raise ManagerUnavailableError(
            "FakeManagerModel has no configured response or exception"
        )


__all__ = ["FakeManagerModel"]
