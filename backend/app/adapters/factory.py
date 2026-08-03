"""Builds and registers agent adapters from application settings.

Called once during FastAPI lifespan startup. Never raises for an optional
agent being disabled or unavailable — only a genuine registry-level error
(e.g. duplicate registration) propagates.
"""

import logging
import shutil

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
}


def _build_profile(agent_type: str, settings: Settings) -> CLIProfile | None:
    try:
        if agent_type == AgentType.CLAUDE_CODE.value:
            return settings.claude_code_profile()
        if agent_type == AgentType.CODEX.value:
            return settings.codex_profile()
        if agent_type == AgentType.GEMINI.value:
            return settings.gemini_profile()
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

    for agent_type in (AgentType.CLAUDE_CODE.value, AgentType.CODEX.value, AgentType.GEMINI.value):
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
