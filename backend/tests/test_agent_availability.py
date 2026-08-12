"""Tests for the agent-availability reporting service."""

from unittest.mock import patch

from app.adapters.demo import DemoAgentAdapter
from app.core.config import Settings
from app.engine.registry import ExecutorRegistry
from app.services.agent_availability import list_agent_availability


def test_all_canonical_agent_types_are_reported() -> None:
    settings = Settings()
    registry = ExecutorRegistry()

    results = list_agent_availability(settings, registry)

    assert {item.agent_type for item in results} == {
        "claude_code",
        "codex",
        "antigravity",
        "gemini",
        "demo",
    }


def test_zero_config_discovery_reports_truthful_status_without_config_gating() -> None:
    settings = Settings()
    # Static config flags are False by default
    assert settings.codex_enabled is False
    registry = ExecutorRegistry()

    results = list_agent_availability(settings, registry)

    for item in results:
        # Static config flag does NOT block discovery
        assert item.reason != "Disabled by configuration" or item.agent_type == "demo"


def test_missing_executable_reports_not_detected() -> None:
    settings = Settings(claude_code_executable="does-not-exist-anywhere")
    registry = ExecutorRegistry()

    with patch(
        "app.services.runtime_discovery.BaseRuntimeDiscoveryStrategy.find_executable",
        return_value=None,
    ):
        results = list_agent_availability(settings, registry)

    claude = next(item for item in results if item.agent_type == "claude_code")
    assert claude.enabled is False
    assert claude.available is False
    assert claude.installation_status == "not_installed"
    assert claude.reason == "Executable not detected"


def test_registered_adapters_report_registered() -> None:
    settings = Settings(demo_enabled=True)
    registry = ExecutorRegistry()
    registry.register("demo", DemoAgentAdapter())

    results = list_agent_availability(settings, registry)

    demo = next(item for item in results if item.agent_type == "demo")
    assert demo.registered is True

    claude = next(item for item in results if item.agent_type == "claude_code")
    assert claude.registered is False


def test_absolute_executable_paths_are_not_exposed() -> None:
    settings = Settings(claude_code_executable="claude")
    registry = ExecutorRegistry()

    results = list_agent_availability(settings, registry)

    for item in results:
        assert "C:\\" not in item.reason
        assert "/" not in item.reason or "PATH" in item.reason


def test_availability_response_count_is_correct() -> None:
    settings = Settings()
    registry = ExecutorRegistry()

    results = list_agent_availability(settings, registry)

    assert len(results) == 5


def test_stable_ordering_is_preserved() -> None:
    settings = Settings()
    registry = ExecutorRegistry()

    results = list_agent_availability(settings, registry)

    assert [item.agent_type for item in results] == [
        "claude_code",
        "codex",
        "antigravity",
        "gemini",
        "demo",
    ]


def test_invalid_configuration_reports_safely() -> None:
    settings = Settings(
        claude_code_input_mode="stdin",
        claude_code_arguments=["{prompt}"],  # invalid: placeholder not allowed for stdin mode
    )
    registry = ExecutorRegistry()

    results = list_agent_availability(settings, registry)

    claude = next(item for item in results if item.agent_type == "claude_code")
    assert claude.available is False
    assert claude.reason == "Invalid configuration"
