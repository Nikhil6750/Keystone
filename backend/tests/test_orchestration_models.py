"""Tests for `app.engine.orchestration.models`."""

import pytest
from pydantic import ValidationError

from app.contracts.enums import AgentCapability
from app.engine.orchestration.models import OrchestrationOutcome, OrchestrationRequest


def test_minimal_request_valid() -> None:
    request = OrchestrationRequest(request_id="req-1", goal="Implement feature X")
    assert request.goal == "Implement feature X"
    assert request.available_agent_types == []
    assert request.available_capabilities == []


def test_rejects_blank_goal() -> None:
    with pytest.raises(ValidationError):
        OrchestrationRequest(request_id="req-1", goal="   ")


def test_rejects_blank_request_id() -> None:
    with pytest.raises(ValidationError):
        OrchestrationRequest(request_id="   ", goal="goal")


def test_rejects_oversized_goal() -> None:
    with pytest.raises(ValidationError):
        OrchestrationRequest(request_id="req-1", goal="x" * 5000)


def test_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        OrchestrationRequest.model_validate(
            {"request_id": "req-1", "goal": "goal", "hidden_reasoning": "leak"}
        )


def test_accepts_known_capabilities_only() -> None:
    request = OrchestrationRequest(
        request_id="req-1", goal="goal", available_capabilities=[AgentCapability.CODE_GENERATION]
    )
    assert request.available_capabilities == [AgentCapability.CODE_GENERATION]


def test_rejects_unknown_capability() -> None:
    with pytest.raises(ValidationError):
        OrchestrationRequest.model_validate(
            {"request_id": "req-1", "goal": "goal", "available_capabilities": ["telekinesis"]}
        )


def test_knowledge_query_optional_and_bounded() -> None:
    request = OrchestrationRequest(request_id="req-1", goal="goal", knowledge_query="auth notes")
    assert request.knowledge_query == "auth notes"
    with pytest.raises(ValidationError):
        OrchestrationRequest(request_id="req-1", goal="goal", knowledge_query="   ")


def test_every_outcome_is_a_string_enum_value() -> None:
    for outcome in OrchestrationOutcome:
        assert isinstance(outcome.value, str)
        assert outcome.value
