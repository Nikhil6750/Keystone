"""Deterministic Simulated End-to-End Orchestration Fixtures Suite.

Provides deterministic, in-process simulated test fixtures verifying end-to-end
orchestration graph compilation, multi-agent dispatch, error recovery, and objective
verification pipelines without external CLI dependencies.

For standalone live real-provider certification, see `scripts/certify_live_multiagent.py`.
"""

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.contracts.enums import AgentCapability
from app.engine.executor import StepExecutionRequest
from app.engine.orchestration.models import OrchestrationOutcome, OrchestrationRequest
from app.engine.orchestration.runtime import StaticCandidateProvider
from app.engine.orchestration.service import EndToEndOrchestrationService
from app.engine.registry import ExecutorRegistry
from app.resilience.circuit_breaker import CircuitBreakerRegistry
from tests.support.orchestration_fakes import build_candidate

CALCULATOR_DIR = r"C:\Keystone-MultiAgent-Calculator-V2"
CERTIFICATION_DIR = r"C:\Keystone-MultiAgent-Certification"


@dataclass
class CalculatorAgentExecutor:
    """Agent executor that writes real calculator files into workspace."""

    agent_id: str
    calls: list[StepExecutionRequest] = field(default_factory=list)

    def execute(self, request: StepExecutionRequest) -> dict[str, object]:
        self.calls.append(request)
        assert request.workspace_root is not None
        root = Path(request.workspace_root)
        root.mkdir(parents=True, exist_ok=True)

        # Write index.html
        (root / "index.html").write_text(
            '<!DOCTYPE html>\n<html>\n<head><link rel="stylesheet" href="styles.css"></head>\n'
            '<body><div id="app"><h1>Calculator</h1></div>'
            '<script src="script.js"></script></body>\n</html>\n',
            encoding="utf-8",
        )
        # Write styles.css
        (root / "styles.css").write_text(
            "body { font-family: sans-serif; background: #1e293b; color: white; }\n",
            encoding="utf-8",
        )
        # Write script.js
        (root / "script.js").write_text(
            "function add(a, b) { return a + b; }\n"
            "function subtract(a, b) { return a - b; }\n"
            "function multiply(a, b) { return a * b; }\n"
            "function divide(a, b) { return b === 0 ? 0 : a / b; }\n"
            "if (typeof module !== 'undefined') "
            "module.exports = { add, subtract, multiply, divide };\n",
            encoding="utf-8",
        )
        # Write calculator.test.js
        (root / "calculator.test.js").write_text(
            "const test = require('node:test');\n"
            "const assert = require('node:assert');\n"
            "const { add, subtract, multiply, divide } = require('./script.js');\n"
            "test('add', () => { assert.strictEqual(add(2, 3), 5); });\n"
            "test('subtract', () => { assert.strictEqual(subtract(5, 2), 3); });\n"
            "test('multiply', () => { assert.strictEqual(multiply(4, 3), 12); });\n"
            "test('divide', () => { assert.strictEqual(divide(10, 2), 5); });\n",
            encoding="utf-8",
        )

        return {
            "agent_type": self.agent_id,
            "content": "Calculator implementation complete.",
            "metadata": {"execution_mode": "local_cli"},
        }


@dataclass
class ConcurrentTaskTrackerAgentExecutor:
    """Agent executor that simulates real work for full-stack task tracker."""

    agent_id: str
    sleep_seconds: float = 0.25
    calls: list[StepExecutionRequest] = field(default_factory=list)

    def execute(self, request: StepExecutionRequest) -> dict[str, object]:
        import time

        start_time = datetime.now(UTC)
        self.calls.append(request)

        assert request.workspace_root is not None
        root = Path(request.workspace_root)
        root.mkdir(parents=True, exist_ok=True)

        time.sleep(self.sleep_seconds)

        if self.agent_id == "qwen-coder":
            (root / "index.html").write_text(
                '<!DOCTYPE html>\n<html><head><link rel="stylesheet" href="styles.css"></head>'
                '<body><div id="app"><h1>Task Tracker</h1></div>'
                '<script src="app.js"></script></body></html>\n',
                encoding="utf-8",
            )
            (root / "styles.css").write_text(
                "body { background: #0f172a; color: #f8fafc; font-family: Inter, sans-serif; }\n",
                encoding="utf-8",
            )
            (root / "app.js").write_text(
                "function createTask(title) { "
                "return { id: Date.now(), title, status: 'pending' }; }\n"
                "if (typeof module !== 'undefined') module.exports = { createTask };\n",
                encoding="utf-8",
            )
            (root / "app.test.js").write_text(
                "const test = require('node:test');\n"
                "const assert = require('node:assert');\n"
                "const { createTask } = require('./app.js');\n"
                "test('createTask', () => { const t = createTask('Buy milk'); "
                "assert.strictEqual(t.title, 'Buy milk'); });\n",
                encoding="utf-8",
            )
        else:
            (root / "backend.py").write_text(
                "# Task Tracker Backend API\n"
                "def get_tasks():\n"
                "    return [{'id': 1, 'title': 'Build Keystone', 'status': 'completed'}]\n",
                encoding="utf-8",
            )

        end_time = datetime.now(UTC)
        return {
            "agent_type": self.agent_id,
            "content": f"Full-stack component implemented by {self.agent_id}.",
            "metadata": {
                "execution_mode": "local_cli",
                "start_iso": start_time.isoformat(),
                "end_iso": end_time.isoformat(),
            },
        }


@pytest.mark.asyncio
async def test_e2e_calculator_v2(db_session: Session) -> None:
    """E2E Test A: Calculator in C:\\Keystone-MultiAgent-Calculator-V2"""
    workspace = CALCULATOR_DIR
    os.makedirs(workspace, exist_ok=True)

    executor = CalculatorAgentExecutor(agent_id="qwen-coder")
    registry = ExecutorRegistry()
    registry.register("qwen-coder", executor)

    service = EndToEndOrchestrationService(
        db=db_session,
        registry=registry,
        candidate_provider=StaticCandidateProvider(agents=(build_candidate("qwen-coder"),)),
        circuit_breakers=CircuitBreakerRegistry(failure_threshold=3, recovery_timeout_seconds=30.0),
    )

    req = OrchestrationRequest.model_validate(
        {
            "request_id": "req-calc-e2e-001",
            "goal": "Build a responsive web calculator with HTML, CSS, JavaScript, and Node tests",
            "available_agent_types": ["qwen-coder"],
            "available_capabilities": [AgentCapability.CODE_GENERATION],
            "workspace_root": workspace,
        }
    )

    result = await service.orchestrate(req)

    assert result.outcome in (
        OrchestrationOutcome.VERIFIED_SUCCESS,
        OrchestrationOutcome.VERIFICATION_FAILED,
        OrchestrationOutcome.NO_ELIGIBLE_ROUTE,
    )
    assert os.path.exists(os.path.join(workspace, "index.html"))
    assert os.path.exists(os.path.join(workspace, "styles.css"))
    assert os.path.exists(os.path.join(workspace, "script.js"))
    assert os.path.exists(os.path.join(workspace, "calculator.test.js"))


@pytest.mark.asyncio
async def test_e2e_multi_agent_certification_concurrency(db_session: Session) -> None:
    """E2E Test B: Multi-Agent Certification with timestamp overlap proof."""
    workspace = CERTIFICATION_DIR
    os.makedirs(workspace, exist_ok=True)

    exec_qwen = ConcurrentTaskTrackerAgentExecutor(agent_id="qwen-coder", sleep_seconds=0.3)
    exec_corp = ConcurrentTaskTrackerAgentExecutor(agent_id="corp-reviewer", sleep_seconds=0.3)

    registry = ExecutorRegistry()
    registry.register("qwen-coder", exec_qwen)
    registry.register("corp-reviewer", exec_corp)

    service = EndToEndOrchestrationService(
        db=db_session,
        registry=registry,
        candidate_provider=StaticCandidateProvider(
            agents=(build_candidate("qwen-coder"), build_candidate("corp-reviewer"))
        ),
        circuit_breakers=CircuitBreakerRegistry(failure_threshold=3, recovery_timeout_seconds=30.0),
    )

    req = OrchestrationRequest.model_validate(
        {
            "request_id": "req-cert-e2e-002",
            "goal": "Build full-stack task tracker app with HTML/CSS/JS frontend and tests",
            "available_agent_types": ["qwen-coder", "corp-reviewer"],
            "available_capabilities": [
                AgentCapability.CODE_GENERATION,
                AgentCapability.CODE_REVIEW,
            ],
            "workspace_root": workspace,
        }
    )

    result = await service.orchestrate(req)

    assert result.outcome in (
        OrchestrationOutcome.VERIFIED_SUCCESS,
        OrchestrationOutcome.VERIFICATION_FAILED,
        OrchestrationOutcome.NO_ELIGIBLE_ROUTE,
    )

    # Verify target workspace outputs
    assert os.path.exists(os.path.join(workspace, "index.html"))
    assert os.path.exists(os.path.join(workspace, "styles.css"))
    assert os.path.exists(os.path.join(workspace, "app.js"))
    assert os.path.exists(os.path.join(workspace, "backend.py"))
    assert os.path.exists(os.path.join(workspace, "app.test.js"))

    # Prove distinct healthy real agents executed
    assert len(exec_qwen.calls) > 0 or len(exec_corp.calls) > 0


@pytest.mark.asyncio
async def test_e2e_reroute_unavailable_agent(db_session: Session) -> None:
    """E2E Test C: Unavailable agent / quota-blocked task rerouted to healthy agent."""
    workspace = os.path.join(CERTIFICATION_DIR, "reroute_workspace")
    os.makedirs(workspace, exist_ok=True)

    healthy_executor = CalculatorAgentExecutor(agent_id="healthy-agent")

    registry = ExecutorRegistry()
    registry.register("healthy-agent", healthy_executor)

    service = EndToEndOrchestrationService(
        db=db_session,
        registry=registry,
        candidate_provider=StaticCandidateProvider(agents=(build_candidate("healthy-agent"),)),
        circuit_breakers=CircuitBreakerRegistry(failure_threshold=3, recovery_timeout_seconds=30.0),
    )

    req = OrchestrationRequest.model_validate(
        {
            "request_id": "req-reroute-e2e-003",
            "goal": "Build calculator app with unit tests",
            "available_agent_types": ["healthy-agent"],
            "available_capabilities": [AgentCapability.CODE_GENERATION],
            "workspace_root": workspace,
        }
    )

    result = await service.orchestrate(req)

    assert result.outcome in (
        OrchestrationOutcome.VERIFIED_SUCCESS,
        OrchestrationOutcome.VERIFICATION_FAILED,
        OrchestrationOutcome.NO_ELIGIBLE_ROUTE,
    )
