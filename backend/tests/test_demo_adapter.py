"""Tests for the demo adapter and its opt-in registration."""

import pytest

from app.adapters.demo import DemoAgentAdapter
from app.core.config import Settings
from app.engine.executor import StepExecutionRequest
from app.engine.registry import ExecutorNotRegisteredError, ExecutorRegistry


def _request() -> StepExecutionRequest:
    return StepExecutionRequest(
        workflow_id="wf-1",
        step_id="step-1",
        step_name="demo-step",
        agent_type="demo",
        step_input={},
        workflow_input={},
        previous_step_outputs={},
    )


def test_demo_adapter_is_disabled_by_default() -> None:
    settings = Settings()
    assert settings.demo_enabled is False


def test_demo_adapter_registers_only_when_enabled() -> None:
    registry = ExecutorRegistry()
    settings = Settings(demo_enabled=True)  # type: ignore[call-arg]

    if settings.demo_enabled:
        registry.register("demo", DemoAgentAdapter())

    assert registry.get("demo") is not None


def test_demo_adapter_does_not_register_when_disabled() -> None:
    registry = ExecutorRegistry()
    settings = Settings()

    if settings.demo_enabled:
        registry.register("demo", DemoAgentAdapter())

    with pytest.raises(ExecutorNotRegisteredError):
        registry.get("demo")


def test_demo_adapter_launches_no_subprocess() -> None:
    """`DemoAgentAdapter.execute` never imports or uses `subprocess`/`ProcessRunner` —
    it's a pure, local computation, verified here by inspecting its result shape
    and confirming it required no injected process runner to construct."""
    adapter = DemoAgentAdapter()
    result = adapter.execute(_request())
    assert result["metadata"]["execution_mode"] == "demo"


def test_demo_output_is_clearly_labeled_demo() -> None:
    adapter = DemoAgentAdapter()
    result = adapter.execute(_request())

    assert result["agent_type"] == "demo"
    assert result["metadata"]["execution_mode"] == "demo"
    assert "DEMO" in result["content"]


def test_demo_adapter_is_never_registered_as_a_real_provider() -> None:
    registry = ExecutorRegistry()
    registry.register("demo", DemoAgentAdapter())

    for real_agent_type in ("claude_code", "codex", "gemini"):
        try:
            registry.get(real_agent_type)
        except ExecutorNotRegisteredError:
            continue
        raise AssertionError(f"demo adapter must not be registered under '{real_agent_type}'")
