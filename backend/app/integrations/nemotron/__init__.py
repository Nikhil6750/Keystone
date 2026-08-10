"""Stage 8B: the production `NemotronManagerModel` adapter, implementing
Stage 8A's `app.engine.manager.protocol.ManagerModel` Protocol against
NVIDIA Nemotron 3 Ultra's OpenAI-compatible `/v1/chat/completions` surface.

Certified against the Stage 8B0 spike (`docs/stage8/nemotron-integration
-spike.md`, commit `6d7afeafc030b26029589535b56ad2bd05704d0d`). No NVIDIA
SDK, no MCP/tool-execution loop, no NIM deployment management, no model
download, and no chain-of-thought persistence anywhere in this package --
see each module's docstring for the specific boundary it enforces.

Stage 8A (`app.engine.manager`) remains fully authoritative: this package
only ever produces a `ManagerResponse` for Stage 8A's own
`ManagerProposalValidator`/`ManagerOrchestrator` to accept, reject, or fall
back from -- it never bypasses either.
"""

from app.integrations.nemotron.adapter import NemotronManagerModel
from app.integrations.nemotron.config import NemotronConfig
from app.integrations.nemotron.fake import FakeNemotronTransport
from app.integrations.nemotron.transport import (
    HttpxNemotronTransport,
    NemotronTransport,
    TransportRequest,
    TransportResponse,
)

__all__ = [
    "FakeNemotronTransport",
    "HttpxNemotronTransport",
    "NemotronConfig",
    "NemotronManagerModel",
    "NemotronTransport",
    "TransportRequest",
    "TransportResponse",
]
