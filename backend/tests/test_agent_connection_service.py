"""Tests for `app.services.agent_connection.verify_agent` and the
agent-connection cache's TTL behavior."""

import time

import pytest

from app.adapters.connection import AgentConnectionCache, ConnectionStatus
from app.core.config import Settings
from app.engine.registry import ExecutorRegistry
from app.services.agent_connection import (
    UnknownAgentTypeError,
    VerificationInProgressError,
    verify_agent,
)


def test_unknown_agent_type_is_rejected() -> None:
    settings = Settings()
    registry = ExecutorRegistry()
    cache = AgentConnectionCache(cache_seconds=60.0)

    with pytest.raises(UnknownAgentTypeError):
        verify_agent("not-a-real-agent", settings, registry, cache)


def test_disabled_agent_reports_disabled_without_touching_the_registry() -> None:
    settings = Settings(claude_code_enabled=False)
    registry = ExecutorRegistry()
    cache = AgentConnectionCache(cache_seconds=60.0)

    state = verify_agent("claude_code", settings, registry, cache)

    assert state.connection_status is ConnectionStatus.DISABLED


def test_enabled_but_unregistered_agent_reports_unavailable() -> None:
    settings = Settings(claude_code_enabled=True)
    registry = ExecutorRegistry()
    cache = AgentConnectionCache(cache_seconds=60.0)

    state = verify_agent("claude_code", settings, registry, cache)

    assert state.connection_status is ConnectionStatus.UNAVAILABLE


def test_result_is_cached_after_verification() -> None:
    settings = Settings()
    registry = ExecutorRegistry()
    cache = AgentConnectionCache(cache_seconds=60.0)

    verify_agent("demo", settings, registry, cache)

    assert cache.get("demo") is not None


def test_cache_expires_after_the_configured_window() -> None:
    settings = Settings()
    registry = ExecutorRegistry()
    cache = AgentConnectionCache(cache_seconds=0.05)

    verify_agent("demo", settings, registry, cache)
    assert cache.get("demo") is not None

    time.sleep(0.1)

    assert cache.get("demo") is None


def test_concurrent_verification_of_the_same_agent_type_conflicts() -> None:
    settings = Settings()
    registry = ExecutorRegistry()
    cache = AgentConnectionCache(cache_seconds=60.0)

    assert cache.try_begin_verification("demo") is True
    try:
        with pytest.raises(VerificationInProgressError):
            verify_agent("demo", settings, registry, cache)
    finally:
        cache.end_verification("demo")
