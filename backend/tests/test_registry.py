"""Tests for the in-process executor registry."""

from typing import Any

import pytest

from app.engine.executor import StepExecutionRequest
from app.engine.registry import ExecutorNotRegisteredError, ExecutorRegistry


class _StubExecutor:
    def execute(self, request: StepExecutionRequest) -> dict[str, Any]:
        return {}


def test_register_and_retrieve_executor_succeeds() -> None:
    registry = ExecutorRegistry()
    executor = _StubExecutor()

    registry.register("mock", executor)

    assert registry.get("mock") is executor


def test_agent_types_are_normalized_consistently() -> None:
    registry = ExecutorRegistry()
    executor = _StubExecutor()

    registry.register("  Mock-Agent  ", executor)

    assert registry.get("mock-agent") is executor
    assert registry.get("MOCK-AGENT") is executor


def test_blank_agent_type_is_rejected_on_register() -> None:
    registry = ExecutorRegistry()
    with pytest.raises(ValueError, match="blank"):
        registry.register("   ", _StubExecutor())


def test_blank_agent_type_is_rejected_on_get() -> None:
    registry = ExecutorRegistry()
    with pytest.raises(ValueError, match="blank"):
        registry.get("   ")


def test_duplicate_registration_is_rejected_by_default() -> None:
    registry = ExecutorRegistry()
    registry.register("mock", _StubExecutor())

    with pytest.raises(ValueError, match="already registered"):
        registry.register("mock", _StubExecutor())


def test_explicit_replacement_works_when_requested() -> None:
    registry = ExecutorRegistry()
    first = _StubExecutor()
    second = _StubExecutor()
    registry.register("mock", first)

    registry.register("mock", second, replace=True)

    assert registry.get("mock") is second


def test_missing_executor_lookup_raises_focused_exception() -> None:
    registry = ExecutorRegistry()
    with pytest.raises(ExecutorNotRegisteredError):
        registry.get("unknown")


def test_separate_registry_instances_do_not_share_state() -> None:
    registry_a = ExecutorRegistry()
    registry_b = ExecutorRegistry()
    registry_a.register("mock", _StubExecutor())

    assert registry_a.get("mock") is not None
    with pytest.raises(ExecutorNotRegisteredError):
        registry_b.get("mock")
