"""Tests for `build_routing_request` (TaskSpec -> RoutingRequest translation)
and the `classify_task_type` raw-text fallback."""

from app.contracts.adapter import RepositoryMetadata
from app.contracts.enums import AgentCapability
from app.contracts.planning import TaskSpec
from app.contracts.routing import RoutingConstraints
from app.engine.routing.classifier import DEFAULT_TASK_TYPE, RuleBasedTaskClassifier
from app.engine.routing.request_builder import build_routing_request, classify_task_type


def _task(**overrides: object) -> TaskSpec:
    base: dict[str, object] = {"key": "a", "name": "step-a", "task_type": "debugging"}
    base.update(overrides)
    return TaskSpec.model_validate(base)


def test_task_type_is_preserved_verbatim() -> None:
    task = _task(task_type="code_review")
    request = build_routing_request(task)
    assert request.task_type == "code_review"


def test_required_capabilities_are_preserved() -> None:
    task = _task(
        required_capabilities=[AgentCapability.CODE_REVIEW, AgentCapability.TEST_EXECUTION]
    )
    request = build_routing_request(task)
    assert request.required_capabilities == [
        AgentCapability.CODE_REVIEW,
        AgentCapability.TEST_EXECUTION,
    ]


def test_no_provider_is_ever_chosen_by_the_builder() -> None:
    """`TaskSpec` structurally cannot carry an `agent_type` (Stage 4A), and
    the builder must not invent one either — routing/manual-override
    selection is untouched unless the caller explicitly supplies it."""
    request = build_routing_request(_task())
    assert request.candidate_agent_types is None
    assert request.manual_override_agent_type is None


def test_manual_override_is_passed_through_when_supplied() -> None:
    request = build_routing_request(_task(), manual_override_agent_type="claude_code")
    assert request.manual_override_agent_type == "claude_code"


def test_candidate_agent_types_is_passed_through_when_supplied() -> None:
    request = build_routing_request(_task(), candidate_agent_types=["claude_code", "codex"])
    assert request.candidate_agent_types == ["claude_code", "codex"]


def test_constraints_default_to_a_permissive_routing_constraints() -> None:
    request = build_routing_request(_task())
    assert request.constraints == RoutingConstraints()


def test_constraints_are_passed_through_when_supplied() -> None:
    constraints = RoutingConstraints(excluded_agent_types=["codex"], max_cost_usd=1.0)
    request = build_routing_request(_task(), constraints=constraints)
    assert request.constraints == constraints


def test_repository_is_passed_through_when_supplied() -> None:
    repository = RepositoryMetadata(repository_id="repo-1", name="keystone")
    request = build_routing_request(_task(), repository=repository)
    assert request.repository == repository


def test_repository_defaults_to_none() -> None:
    request = build_routing_request(_task())
    assert request.repository is None


def test_classify_task_type_uses_the_default_rule_based_classifier() -> None:
    assert classify_task_type("please review this pull request") == "code_review"


def test_classify_task_type_falls_back_to_default_task_type_for_unmatched_text() -> None:
    assert classify_task_type("do the thing") == DEFAULT_TASK_TYPE


def test_classify_task_type_accepts_a_custom_classifier() -> None:
    classifier = RuleBasedTaskClassifier()
    assert classify_task_type("Debug the login flow", classifier) == "debugging"
