"""Tests for the provider-neutral AgentAdapter contract and execution models."""

from typing import Any

import pytest
from pydantic import ValidationError

from app.contracts.adapter import (
    AgentAdapter,
    AgentDescriptor,
    AgentExecutionRequest,
    AgentExecutionResult,
)
from app.contracts.enums import AgentCapability, AgentExecutionStatus, AgentStatus
from app.contracts.errors import FailureCategory


def _request(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "agent_id": "claude_code-1",
        "agent_type": "claude_code",
        "execution_id": "exec-1",
        "workflow_id": "wf-1",
        "step_id": "step-1",
        "task_type": "code_generation",
        "timeout_seconds": 30.0,
    }
    base.update(overrides)
    return base


def test_execution_request_requires_positive_timeout() -> None:
    with pytest.raises(ValidationError):
        AgentExecutionRequest.model_validate(_request(timeout_seconds=0))


def test_execution_request_requires_positive_attempt_number() -> None:
    with pytest.raises(ValidationError):
        AgentExecutionRequest.model_validate(_request(attempt_number=0))


def test_execution_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        AgentExecutionRequest.model_validate(_request(unexpected_field="nope"))


def test_execution_request_provider_detail_stays_in_metadata() -> None:
    request = AgentExecutionRequest.model_validate(
        _request(metadata={"raw_cli_flag": "--yolo"})
    )
    assert request.metadata == {"raw_cli_flag": "--yolo"}


def test_execution_result_failed_requires_failure_category() -> None:
    with pytest.raises(ValidationError):
        AgentExecutionResult.model_validate(
            {
                "agent_id": "claude_code-1",
                "agent_type": "claude_code",
                "execution_id": "exec-1",
                "workflow_id": "wf-1",
                "step_id": "step-1",
                "status": AgentExecutionStatus.FAILED,
            }
        )


def test_execution_result_succeeded_does_not_require_failure_category() -> None:
    result = AgentExecutionResult.model_validate(
        {
            "agent_id": "claude_code-1",
            "agent_type": "claude_code",
            "execution_id": "exec-1",
            "workflow_id": "wf-1",
            "step_id": "step-1",
            "status": AgentExecutionStatus.SUCCEEDED,
            "output_payload": {"ok": True},
        }
    )
    assert result.failure_category is None
    assert result.output_payload == {"ok": True}


def _result(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "agent_id": "claude_code-1",
        "agent_type": "claude_code",
        "execution_id": "exec-1",
        "workflow_id": "wf-1",
        "step_id": "step-1",
    }
    base.update(overrides)
    return base


def test_execution_result_succeeded_with_failure_category_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentExecutionResult.model_validate(
            _result(status=AgentExecutionStatus.SUCCEEDED, failure_category=FailureCategory.TIMEOUT)
        )


def test_execution_result_cancelled_requires_cancelled_category() -> None:
    with pytest.raises(ValidationError):
        AgentExecutionResult.model_validate(_result(status=AgentExecutionStatus.CANCELLED))


def test_execution_result_cancelled_with_wrong_category_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentExecutionResult.model_validate(
            _result(
                status=AgentExecutionStatus.CANCELLED,
                failure_category=FailureCategory.PROVIDER_ERROR,
            )
        )


def test_execution_result_cancelled_with_matching_category_is_accepted() -> None:
    result = AgentExecutionResult.model_validate(
        _result(status=AgentExecutionStatus.CANCELLED, failure_category=FailureCategory.CANCELLED)
    )
    assert result.status is AgentExecutionStatus.CANCELLED


def test_execution_result_timed_out_requires_timeout_category() -> None:
    with pytest.raises(ValidationError):
        AgentExecutionResult.model_validate(_result(status=AgentExecutionStatus.TIMED_OUT))


def test_execution_result_timed_out_with_wrong_category_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentExecutionResult.model_validate(
            _result(
                status=AgentExecutionStatus.TIMED_OUT,
                failure_category=FailureCategory.NETWORK_ERROR,
            )
        )


def test_execution_result_timed_out_with_matching_category_is_accepted() -> None:
    result = AgentExecutionResult.model_validate(
        _result(status=AgentExecutionStatus.TIMED_OUT, failure_category=FailureCategory.TIMEOUT)
    )
    assert result.status is AgentExecutionStatus.TIMED_OUT


def test_execution_result_never_silently_rewrites_a_mismatched_category() -> None:
    """A mismatched category must raise, not get silently coerced to match
    the status — validation failure is the only allowed outcome here."""
    with pytest.raises(ValidationError) as exc_info:
        AgentExecutionResult.model_validate(
            _result(
                status=AgentExecutionStatus.CANCELLED,
                failure_category=FailureCategory.INTERNAL_ERROR,
            )
        )
    assert "CANCELLED" in str(exc_info.value)


def test_execution_result_contains_no_credential_fields() -> None:
    fields = set(AgentExecutionResult.model_fields)
    for forbidden in ("token", "credential", "password", "secret", "session"):
        assert not any(forbidden in field.lower() for field in fields)


class _StubAdapter:
    """A minimal concrete implementation used to verify the protocol shape."""

    def describe(self) -> AgentDescriptor:
        return AgentDescriptor(
            agent_type="demo",
            display_name="Demo",
            capabilities=[AgentCapability.GENERAL_REASONING],
        )

    def capabilities(self) -> list[AgentCapability]:
        return [AgentCapability.GENERAL_REASONING]

    async def verify(self) -> AgentStatus:
        return AgentStatus.AVAILABLE

    async def health(self) -> AgentStatus:
        return AgentStatus.AVAILABLE

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        return AgentExecutionResult(
            agent_id=request.agent_id,
            agent_type=request.agent_type,
            execution_id=request.execution_id,
            workflow_id=request.workflow_id,
            step_id=request.step_id,
            status=AgentExecutionStatus.SUCCEEDED,
            output_payload={},
        )

    async def cancel(self, execution_id: str) -> bool:
        return False


def test_stub_adapter_satisfies_the_protocol() -> None:
    adapter: AgentAdapter = _StubAdapter()
    assert adapter.describe().agent_type == "demo"


async def test_stub_adapter_execute_round_trips() -> None:
    adapter: AgentAdapter = _StubAdapter()
    result = await adapter.execute(AgentExecutionRequest.model_validate(_request()))
    assert result.status is AgentExecutionStatus.SUCCEEDED
