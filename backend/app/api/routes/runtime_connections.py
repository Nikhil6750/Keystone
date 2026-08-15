"""Runtime activation API — the deliberate, user-triggered seam between a
detected-but-disabled local CLI runtime (`GET /api/v1/agents`) and an
executable one, for the Connect Agent "Installed / Sign in" flow.

Never flips every adapter to enabled by default: activation is scoped to
exactly the one `runtime_id` the user clicked "Connect" on, and only
succeeds if the executable is genuinely found on PATH. Never accepts or
returns a credential — see `app.adapters.claude_code.ClaudeCodeAdapter`
for why local CLI runtimes need none.
"""

from fastapi import APIRouter, Depends

from app.adapters.connection import AgentConnectionCache
from app.adapters.factory import UnknownRuntimeError, activate_agent
from app.api.deps import get_agent_connection_cache, get_executor_registry
from app.core.config import Settings, get_settings
from app.engine.registry import ExecutorRegistry
from app.schemas.agents import AgentConnectionVerifyRead
from app.services.agent_availability import capabilities_for
from app.services.agent_connection import UnknownAgentTypeError, verify_agent

router = APIRouter(prefix="/runtime-connections", tags=["runtime-connections"])


@router.post(
    "/{runtime_id}/activate",
    response_model=AgentConnectionVerifyRead,
    summary="Deliberately activate one installed runtime",
)
def activate_runtime_connection(
    runtime_id: str,
    settings: Settings = Depends(get_settings),  # noqa: B008
    registry: ExecutorRegistry = Depends(get_executor_registry),  # noqa: B008
    cache: AgentConnectionCache = Depends(get_agent_connection_cache),  # noqa: B008
) -> AgentConnectionVerifyRead:
    """Registers `runtime_id`'s adapter (if its executable is found on PATH)
    and returns one fresh, real verification of it -- same truthful
    installation/authentication/connection status contract as
    `POST /agents/{agent_type}/verify`, so the caller never has to reconcile
    two different shapes for "is this runtime actually usable."

    Raises `404 AGENT_TYPE_UNKNOWN` for a non-canonical runtime id. Never
    raises for a genuinely-not-installed runtime -- that is a normal,
    truthful `installation_status=not_installed` response, not an error.
    """
    try:
        activate_agent(registry, settings, runtime_id)
    except UnknownRuntimeError as exc:
        raise UnknownAgentTypeError(runtime_id) from exc

    state = verify_agent(runtime_id, settings, registry, cache)
    response = AgentConnectionVerifyRead.model_validate(state)
    return response.model_copy(update={"capabilities": capabilities_for(runtime_id)})
