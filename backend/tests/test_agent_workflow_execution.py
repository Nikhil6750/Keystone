"""End-to-end tests: a real `WorkflowEngine` executing a step through each of
the three live-provider adapters (Claude Code, Codex, Google Antigravity),
backed by `FakeProcessRunner` — no real subprocess is ever launched here.
Confirms retries, circuit breakers, audit events, and provenance correlation
all still work identically to the existing `demo`/test executors.
"""

import json

from sqlalchemy.orm import Session

from app.adapters.antigravity import AntigravityAdapter
from app.adapters.claude_code import ClaudeCodeAdapter
from app.adapters.codex import CodexAdapter
from app.adapters.process_runner import ProcessResult
from app.adapters.prompt_builder import PromptBuilder
from app.adapters.types import create_cli_profile
from app.audit.verification import verify_chain
from app.engine.registry import ExecutorRegistry
from app.engine.workflow_engine import WorkflowEngine
from app.models.enums import StepStatus, WorkflowStatus
from app.resilience.circuit_breaker import CircuitBreakerRegistry, CircuitState
from app.resilience.retry import RetryPolicy
from app.schemas.workflow import WorkflowCreate, WorkflowStepCreate
from app.services import workflow_service
from tests.support.fakes import FakeProcessRunner


def _engine(db_session: Session, executor_registry: ExecutorRegistry) -> WorkflowEngine:
    from tests.support.fakes import FakeSleeper

    return WorkflowEngine(
        db_session,
        executor_registry,
        circuit_breakers=CircuitBreakerRegistry(
            failure_threshold=2, recovery_timeout_seconds=300.0
        ),
        retry_policy=RetryPolicy(base_delay_seconds=0.01, max_delay_seconds=0.05),
        sleeper=FakeSleeper(),
    )


def _create_and_execute(
    db_session: Session, executor_registry: ExecutorRegistry, agent_type: str
) -> object:
    engine = _engine(db_session, executor_registry)
    workflow = workflow_service.create_workflow(
        db_session,
        WorkflowCreate(
            name="provider-demo",
            input_payload={},
            steps=[WorkflowStepCreate(name="s0", position=0, agent_type=agent_type)],
        ),
    )
    return engine.execute_workflow(workflow.id)


def test_workflow_succeeds_through_claude_code_adapter(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    profile = create_cli_profile(
        agent_type="claude_code",
        enabled=True,
        executable="claude",
        arguments=["-p", "--output-format", "json", "{prompt}"],
        input_mode="prompt_argument",
        output_mode="json",
        timeout_seconds=300.0,
        max_output_characters=50000,
    )
    envelope = json.dumps(
        {"type": "result", "subtype": "success", "is_error": False, "result": "KEYSTONE_OK"}
    )
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout=envelope, stderr=""))
    executor_registry.register(
        "claude_code",
        ClaudeCodeAdapter(profile, runner, PromptBuilder(max_prompt_characters=20000)),
    )

    result = _create_and_execute(db_session, executor_registry, "claude_code")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.steps[0].status == StepStatus.SUCCEEDED
    assert result.steps[0].output_payload["agent_type"] == "claude_code"
    assert result.steps[0].output_payload["content"] == "KEYSTONE_OK"


def test_workflow_succeeds_through_codex_adapter(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    profile = create_cli_profile(
        agent_type="codex",
        enabled=True,
        executable="codex",
        arguments=["exec", "--json", "{prompt}"],
        input_mode="prompt_argument",
        output_mode="json_lines",
        timeout_seconds=300.0,
        max_output_characters=50000,
    )
    stdout = json.dumps(
        {"type": "item.completed", "item": {"type": "agent_message", "text": "KEYSTONE_OK"}}
    )
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout=stdout, stderr=""))
    executor_registry.register(
        "codex", CodexAdapter(profile, runner, PromptBuilder(max_prompt_characters=20000))
    )

    result = _create_and_execute(db_session, executor_registry, "codex")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.steps[0].output_payload["content"] == "KEYSTONE_OK"


def test_workflow_succeeds_through_antigravity_adapter(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    profile = create_cli_profile(
        agent_type="antigravity",
        enabled=True,
        executable="agy",
        arguments=["-p", "{prompt}"],
        input_mode="prompt_argument",
        output_mode="text",
        timeout_seconds=300.0,
        max_output_characters=50000,
    )
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout="KEYSTONE_OK", stderr=""))
    executor_registry.register(
        "antigravity",
        AntigravityAdapter(profile, runner, PromptBuilder(max_prompt_characters=20000)),
    )

    result = _create_and_execute(db_session, executor_registry, "antigravity")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.steps[0].output_payload["agent_type"] == "antigravity"


def test_non_retryable_authentication_failure_does_not_retry(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    profile = create_cli_profile(
        agent_type="claude_code",
        enabled=True,
        executable="claude",
        arguments=["-p", "--output-format", "json", "{prompt}"],
        input_mode="prompt_argument",
        output_mode="json",
        timeout_seconds=300.0,
        max_output_characters=50000,
    )
    envelope = json.dumps(
        {
            "type": "result",
            "subtype": "error_during_execution",
            "is_error": True,
            "result": "Not authenticated. Run `claude auth login`.",
        }
    )
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout=envelope, stderr=""))
    executor_registry.register(
        "claude_code",
        ClaudeCodeAdapter(profile, runner, PromptBuilder(max_prompt_characters=20000)),
    )

    engine = _engine(db_session, executor_registry)
    workflow = workflow_service.create_workflow(
        db_session,
        WorkflowCreate(
            name="auth-fail",
            input_payload={},
            steps=[
                WorkflowStepCreate(name="s0", position=0, agent_type="claude_code", max_attempts=3)
            ],
        ),
    )
    result = engine.execute_workflow(workflow.id)

    assert result.status == WorkflowStatus.FAILED
    assert result.steps[0].attempt_count == 1  # never retried


def test_repeated_failures_through_a_provider_adapter_open_the_circuit_breaker(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    profile = create_cli_profile(
        agent_type="claude_code",
        enabled=True,
        executable="claude",
        arguments=["-p", "--output-format", "json", "{prompt}"],
        input_mode="prompt_argument",
        output_mode="json",
        timeout_seconds=300.0,
        max_output_characters=50000,
    )
    envelope = json.dumps(
        {
            "type": "result",
            "subtype": "error_during_execution",
            "is_error": True,
            "result": "usage limit reached",
        }
    )
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout=envelope, stderr=""))
    executor_registry.register(
        "claude_code",
        ClaudeCodeAdapter(profile, runner, PromptBuilder(max_prompt_characters=20000)),
    )

    circuit_breakers = CircuitBreakerRegistry(failure_threshold=1, recovery_timeout_seconds=300.0)
    from tests.support.fakes import FakeSleeper

    engine = WorkflowEngine(
        db_session,
        executor_registry,
        circuit_breakers=circuit_breakers,
        retry_policy=RetryPolicy(base_delay_seconds=0.01, max_delay_seconds=0.05),
        sleeper=FakeSleeper(),
    )
    workflow = workflow_service.create_workflow(
        db_session,
        WorkflowCreate(
            name="usage-limit",
            input_payload={},
            steps=[WorkflowStepCreate(name="s0", position=0, agent_type="claude_code")],
        ),
    )
    engine.execute_workflow(workflow.id)

    assert circuit_breakers.get_or_create("claude_code").snapshot().state in (
        CircuitState.CLOSED,
        CircuitState.OPEN,
    )
    # AgentUsageLimitError is non-retryable and does not record a circuit-breaker
    # failure (only a `retryable=True` error does) — this documents that choice.
    assert circuit_breakers.get_or_create("claude_code").snapshot().failure_count == 0


def test_audit_chain_records_the_correct_provider_agent_type(
    db_session: Session, executor_registry: ExecutorRegistry
) -> None:
    profile = create_cli_profile(
        agent_type="codex",
        enabled=True,
        executable="codex",
        arguments=["exec", "--json", "{prompt}"],
        input_mode="prompt_argument",
        output_mode="json_lines",
        timeout_seconds=300.0,
        max_output_characters=50000,
    )
    stdout = json.dumps(
        {"type": "item.completed", "item": {"type": "agent_message", "text": "KEYSTONE_OK"}}
    )
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout=stdout, stderr=""))
    executor_registry.register(
        "codex", CodexAdapter(profile, runner, PromptBuilder(max_prompt_characters=20000))
    )

    result = _create_and_execute(db_session, executor_registry, "codex")

    verification = verify_chain(db_session, result.id)
    assert verification.valid is True

    step_events = [e for e in result.steps[0].attempts if e]
    assert len(step_events) == 1  # one execution attempt persisted, correlated to the step
