"""Builds and registers agent adapters from application settings.

`register_agents` is called once during FastAPI lifespan startup, respecting
each adapter's static `enabled` config flag. `activate_agent` is the
deliberate, user-triggered counterpart (Stage 8C.3 Connect Agent): it
registers one specific adapter on demand, regardless of the static config
flag, because the caller invoking it *is* the enablement decision -- see
`POST /api/v1/runtime-connections/{runtime_id}/activate`. Neither ever
raises for an optional agent being disabled or unavailable — only a genuine
registry-level error (e.g. duplicate registration without `replace=True`)
propagates.
"""

import dataclasses
import logging
import shutil

from app.adapters.antigravity import AntigravityAdapter
from app.adapters.claude_code import ClaudeCodeAdapter
from app.adapters.codex import CodexAdapter
from app.adapters.demo import DemoAgentAdapter
from app.adapters.gemini import GeminiAdapter
from app.adapters.local_cli import LocalCLIAdapter
from app.adapters.process_runner import ProcessRunner, SubprocessRunner
from app.adapters.prompt_builder import PromptBuilder
from app.adapters.types import AgentType, CLIProfile
from app.core.config import Settings
from app.engine.registry import ExecutorRegistry

logger = logging.getLogger(__name__)

_ADAPTER_CLASSES: dict[str, type[LocalCLIAdapter]] = {
    AgentType.CLAUDE_CODE.value: ClaudeCodeAdapter,
    AgentType.CODEX.value: CodexAdapter,
    AgentType.GEMINI.value: GeminiAdapter,
    AgentType.ANTIGRAVITY.value: AntigravityAdapter,
}

_LOCAL_CLI_AGENT_TYPES = (
    AgentType.CLAUDE_CODE.value,
    AgentType.CODEX.value,
    AgentType.GEMINI.value,
    AgentType.ANTIGRAVITY.value,
)


def _build_profile(agent_type: str, settings: Settings) -> CLIProfile | None:
    try:
        if agent_type == AgentType.CLAUDE_CODE.value:
            return settings.claude_code_profile()
        if agent_type == AgentType.CODEX.value:
            return settings.codex_profile()
        if agent_type == AgentType.GEMINI.value:
            return settings.gemini_profile()
        if agent_type == AgentType.ANTIGRAVITY.value:
            return settings.antigravity_profile()
    except ValueError:
        logger.warning(
            "agent_adapter_unavailable agent_type=%s reason=invalid_configuration", agent_type
        )
        return None
    raise ValueError(f"unknown agent_type '{agent_type}'")


def register_agents(
    registry: ExecutorRegistry,
    settings: Settings,
    *,
    process_runner: ProcessRunner | None = None,
) -> None:
    """Register every enabled-and-available local CLI adapter, plus demo if enabled.

    Never launches a real agent process; only resolves executables via
    `shutil.which` to check availability.
    """
    runner = process_runner or SubprocessRunner()
    prompt_builder = PromptBuilder(max_prompt_characters=settings.agent_max_prompt_characters)

    for agent_type in _LOCAL_CLI_AGENT_TYPES:
        profile = _build_profile(agent_type, settings)
        if profile is None:
            continue
        if not profile.enabled:
            logger.info("agent_adapter_unavailable agent_type=%s reason=disabled", agent_type)
            continue
        if shutil.which(profile.executable) is None:
            logger.warning(
                "agent_adapter_unavailable agent_type=%s reason=executable_not_found", agent_type
            )
            continue
        adapter_cls = _ADAPTER_CLASSES[agent_type]
        registry.register(agent_type, adapter_cls(profile, runner, prompt_builder))
        logger.info("agent_adapter_registered agent_type=%s execution_mode=local_cli", agent_type)

    if settings.demo_enabled:
        registry.register(AgentType.DEMO.value, DemoAgentAdapter())
        logger.info("agent_adapter_registered agent_type=demo execution_mode=demo")
    else:
        logger.info("agent_adapter_unavailable agent_type=demo reason=disabled")


class UnknownRuntimeError(ValueError):
    """Raised when activation is requested for a non-canonical runtime id."""

    def __init__(self, runtime_id: str) -> None:
        self.runtime_id = runtime_id
        super().__init__(f"'{runtime_id}' is not a recognized canonical runtime id")


def activate_agent(
    registry: ExecutorRegistry,
    settings: Settings,
    agent_type: str,
    *,
    process_runner: ProcessRunner | None = None,
) -> bool:
    """Deliberately registers one specific adapter on user request (Connect
    Agent -> Installed / Sign in -> Connect), independent of its static
    `KEYSTONE_<X>_ENABLED` config flag -- the call itself is the user's
    enablement decision. Reuses the same profile-building, argument-safety,
    and adapter-construction logic as startup-time `register_agents` so
    there is exactly one trusted code path for turning settings into a live
    adapter; only the `enabled` gate is overridden here.

    Returns `True` if an adapter is now registered for `agent_type` (either
    already was, or was just registered), `False` if its executable is not
    on PATH. Raises `UnknownRuntimeError` for a non-canonical `agent_type`.
    Never registers anything for an executable that cannot be found --
    activation can never fabricate availability.
    """
    if agent_type == AgentType.DEMO.value:
        if not settings.demo_enabled:
            return False
        registry.register(AgentType.DEMO.value, DemoAgentAdapter(), replace=True)
        logger.info("agent_adapter_activated agent_type=demo execution_mode=demo")
        return True

    if agent_type not in _ADAPTER_CLASSES:
        raise UnknownRuntimeError(agent_type)

    profile = _build_profile(agent_type, settings)
    if profile is None:
        return False
    activated_profile = dataclasses.replace(profile, enabled=True)

    if shutil.which(activated_profile.executable) is None:
        logger.warning(
            "agent_adapter_activation_failed agent_type=%s reason=executable_not_found",
            agent_type,
        )
        return False

    runner = process_runner or SubprocessRunner()
    prompt_builder = PromptBuilder(max_prompt_characters=settings.agent_max_prompt_characters)
    adapter_cls = _ADAPTER_CLASSES[agent_type]
    registry.register(
        agent_type, adapter_cls(activated_profile, runner, prompt_builder), replace=True
    )
    logger.info("agent_adapter_activated agent_type=%s execution_mode=local_cli", agent_type)
    return True
