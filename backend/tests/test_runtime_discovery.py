"""Tests for runtime discovery strategies and zero-config agent availability."""

from pathlib import Path

from app.adapters.connection import InstallationStatus
from app.core.config import Settings
from app.engine.registry import ExecutorRegistry
from app.services.agent_availability import list_agent_availability
from app.services.runtime_discovery import (
    ClaudeCodeDiscoveryStrategy,
    CodexDiscoveryStrategy,
    get_discovery_strategy,
    list_discovery_strategies,
)


def test_list_discovery_strategies_contains_canonical_runtimes():
    strategies = list_discovery_strategies()
    types = [s.runtime_type for s in strategies]
    assert "claude_code" in types
    assert "codex" in types
    assert "antigravity" in types
    assert "gemini" in types
    assert "demo" in types


def test_codex_discovery_strategy_attributes():
    strategy = get_discovery_strategy("codex")
    assert strategy is not None
    assert strategy.runtime_type == "codex"
    assert strategy.display_name == "OpenAI Codex"
    assert strategy.product_kind == "agent_cli"
    assert strategy.execution_supported is True
    assert strategy.supports_sign_in is True


def test_antigravity_discovery_strategy_attributes():
    strategy = get_discovery_strategy("antigravity")
    assert strategy is not None
    assert strategy.runtime_type == "antigravity"
    assert strategy.display_name == "Google Antigravity"
    assert strategy.supports_sign_in is False


def test_gemini_discovery_strategy_separate_from_antigravity():
    antigravity_strat = get_discovery_strategy("antigravity")
    gemini_strat = get_discovery_strategy("gemini")
    assert antigravity_strat is not None
    assert gemini_strat is not None
    assert antigravity_strat.runtime_type != gemini_strat.runtime_type
    assert antigravity_strat.display_name != gemini_strat.display_name

    antigravity_disc = antigravity_strat.discover()
    gemini_disc = gemini_strat.discover()
    assert antigravity_disc.runtime_type != gemini_disc.runtime_type


def test_find_executable_custom_path_override(tmp_path: Path):
    exe = tmp_path / "custom_codex.exe"
    exe.write_text("binary", encoding="utf-8")
    strategy = CodexDiscoveryStrategy()
    resolved = strategy.find_executable(configured_executable=str(exe))
    assert resolved == str(exe.resolve())


def test_find_executable_not_found_returns_none():
    strategy = ClaudeCodeDiscoveryStrategy()
    resolved = strategy.find_executable(configured_executable="non_existent_binary_12345")
    assert resolved is None or Path(resolved).exists()


def test_list_agent_availability_discovers_installed_runtimes_without_config_gating():
    settings = Settings()
    # Explicitly ensure static config flags are False
    assert settings.codex_enabled is False
    assert settings.antigravity_enabled is False
    assert settings.gemini_enabled is False

    registry = ExecutorRegistry()
    reports = list_agent_availability(settings, registry)

    by_type = {r.agent_type: r for r in reports}

    assert "claude_code" in by_type
    assert "codex" in by_type
    assert "antigravity" in by_type
    assert "gemini" in by_type

    # Installed runtimes MUST report INSTALLED even when enabled=False in static config
    codex = by_type["codex"]
    if codex.installation_status == InstallationStatus.INSTALLED:
        assert codex.enabled is True or codex.reason != "Disabled by configuration"

    antigravity = by_type["antigravity"]
    if antigravity.installation_status == InstallationStatus.INSTALLED:
        if antigravity.execution_supported:
            assert antigravity.product_kind == "agent_cli"
        else:
            assert antigravity.product_kind == "ide"
            assert "Execution adapter unavailable" in antigravity.reason
