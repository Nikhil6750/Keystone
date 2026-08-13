"""Tests for the `antigravity` agent-type migration: purely additive, never a
rename or silent alias of `gemini`. See `docs/live-agent-connectors.md`'s
migration-decision section."""

import shutil
from unittest.mock import patch

from app.adapters.antigravity import AntigravityAdapter
from app.adapters.claude_code import ClaudeCodeAdapter
from app.adapters.codex import CodexAdapter
from app.adapters.factory import register_agents
from app.adapters.gemini import GeminiAdapter
from app.adapters.prompt_builder import PromptBuilder
from app.adapters.types import AgentType, create_cli_profile
from app.core.config import Settings
from app.engine.registry import ExecutorNotRegisteredError, ExecutorRegistry
from app.schemas.workflow import WorkflowCreate, WorkflowStepCreate
from app.services import workflow_service
from tests.support.fakes import FakeProcessRunner


def test_gemini_and_antigravity_are_distinct_canonical_values() -> None:
    assert AgentType.GEMINI.value == "gemini"
    assert AgentType.ANTIGRAVITY.value == "antigravity"
    assert AgentType.GEMINI != AgentType.ANTIGRAVITY


def test_all_canonical_agent_types_are_exactly_the_expected_set() -> None:
    assert {member.value for member in AgentType} == {
        "claude_code",
        "codex",
        "gemini",
        "antigravity",
        "demo",
    }


def test_a_persisted_gemini_workflow_step_is_never_silently_executed_via_antigravity(
    db_session: object,
) -> None:
    """A workflow step with `agent_type="gemini"` must resolve strictly through
    the registered `gemini` executor (if any) — never fall back to, or be
    silently redirected to, the `antigravity` adapter."""
    registry = ExecutorRegistry()
    antigravity_profile = create_cli_profile(
        agent_type="antigravity",
        enabled=True,
        executable="agy",
        arguments=["-p", "{prompt}"],
        input_mode="prompt_argument",
        output_mode="text",
        timeout_seconds=5.0,
        max_output_characters=1000,
    )
    registry.register(
        "antigravity",
        AntigravityAdapter(
            antigravity_profile, FakeProcessRunner(), PromptBuilder(max_prompt_characters=1000)
        ),
    )
    # `gemini` is deliberately left unregistered here (disabled by default).

    workflow = workflow_service.create_workflow(
        db_session,
        WorkflowCreate(
            name="legacy-gemini",
            input_payload={},
            steps=[WorkflowStepCreate(name="s0", position=0, agent_type="gemini")],
        ),
    )

    try:
        registry.get(workflow.steps[0].agent_type)
        raised = False
    except ExecutorNotRegisteredError:
        raised = True

    assert raised, "a 'gemini' step must never resolve to the 'antigravity' executor"


def test_factory_registers_antigravity_when_enabled_and_installed() -> None:
    settings = Settings(antigravity_enabled=True, antigravity_executable="mock-agy")
    registry = ExecutorRegistry()

    with patch.object(shutil, "which", return_value="/usr/bin/mock-agy"):
        register_agents(registry, settings, process_runner=FakeProcessRunner())

    assert isinstance(registry.get("antigravity"), AntigravityAdapter)


def test_factory_never_registers_antigravity_when_disabled() -> None:
    settings = Settings(antigravity_enabled=False)
    registry = ExecutorRegistry()

    register_agents(registry, settings, process_runner=FakeProcessRunner())

    try:
        registry.get("antigravity")
        found = True
    except ExecutorNotRegisteredError:
        found = False
    assert not found


def test_factory_registers_the_correct_adapter_class_per_agent_type() -> None:
    settings = Settings(claude_code_enabled=True, codex_enabled=True, antigravity_enabled=True)
    registry = ExecutorRegistry()

    with patch.object(shutil, "which", return_value="/usr/bin/mock"):
        register_agents(registry, settings, process_runner=FakeProcessRunner())

    assert isinstance(registry.get("claude_code"), ClaudeCodeAdapter)
    assert isinstance(registry.get("codex"), CodexAdapter)
    assert isinstance(registry.get("antigravity"), AntigravityAdapter)


def test_gemini_adapter_remains_a_separate_reserved_slot() -> None:
    settings = Settings(gemini_enabled=True)
    registry = ExecutorRegistry()

    with patch.object(shutil, "which", return_value="/usr/bin/mock-gemini"):
        register_agents(registry, settings, process_runner=FakeProcessRunner())

    assert isinstance(registry.get("gemini"), GeminiAdapter)
