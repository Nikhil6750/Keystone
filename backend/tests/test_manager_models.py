"""Structural validation tests for `app.engine.manager.models`.

Every check here exercises the first of Stage 8A's two validation layers
(see `validation.py`'s module docstring): shape, bounds, known enum values,
unique keys, known dependency references, and cycle rejection, all enforced
by Pydantic at construction -- a malformed or oversized `ManagerResponse`
simply cannot exist as a Python object.
"""

import pytest
from pydantic import ValidationError

from app.contracts.enums import AgentCapability, BenchmarkEvaluatorType
from app.contracts.knowledge import KnowledgeSearchResult
from app.contracts.verification import VerificationStatus
from app.engine.manager.models import (
    MAX_TASK_PROPOSALS,
    ManagerEvidenceRef,
    ManagerRecoveryContext,
    ManagerRequest,
    ManagerResponse,
    ManagerTaskProposal,
)
from app.engine.verification.recovery import RecoveryAction


def _task(key: str, **overrides: object) -> ManagerTaskProposal:
    base: dict[str, object] = {"key": key, "description": f"do {key}"}
    base.update(overrides)
    return ManagerTaskProposal.model_validate(base)


# --- ManagerRequest -------------------------------------------------------


def test_manager_request_minimal_valid() -> None:
    request = ManagerRequest(request_id="req-1", goal="Implement feature X")
    assert request.goal == "Implement feature X"
    assert request.available_agent_types == []
    assert request.knowledge_context == []


def test_manager_request_rejects_blank_goal() -> None:
    with pytest.raises(ValidationError):
        ManagerRequest(request_id="req-1", goal="   ")


def test_manager_request_rejects_oversized_goal() -> None:
    with pytest.raises(ValidationError):
        ManagerRequest(request_id="req-1", goal="x" * 5000)


def test_manager_request_rejects_path_like_repository_id() -> None:
    with pytest.raises(ValidationError):
        ManagerRequest(request_id="req-1", goal="goal", repository_id="C:\\secrets\\repo")


def test_manager_request_rejects_traversal_repository_id() -> None:
    with pytest.raises(ValidationError):
        ManagerRequest(request_id="req-1", goal="goal", repository_id="../../etc/passwd")


def test_manager_request_rejects_duplicate_agent_types() -> None:
    with pytest.raises(ValidationError):
        ManagerRequest(
            request_id="req-1",
            goal="goal",
            available_agent_types=["claude_code", "claude_code"],
        )


def test_manager_request_rejects_oversized_agent_type_list() -> None:
    with pytest.raises(ValidationError):
        ManagerRequest(
            request_id="req-1",
            goal="goal",
            available_agent_types=[f"agent-{i}" for i in range(51)],
        )


def test_manager_request_rejects_oversized_knowledge_context() -> None:
    items = [
        KnowledgeSearchResult(
            document_id=f"doc-{i}",
            vault_id="vault",
            title="t",
            snippet="s",
            score=0.5,
        )
        for i in range(21)
    ]
    with pytest.raises(ValidationError):
        ManagerRequest(request_id="req-1", goal="goal", knowledge_context=items)


def test_manager_request_accepts_known_capabilities_only() -> None:
    request = ManagerRequest(
        request_id="req-1",
        goal="goal",
        available_capabilities=[AgentCapability.CODE_GENERATION],
    )
    assert request.available_capabilities == [AgentCapability.CODE_GENERATION]


def test_manager_request_rejects_unknown_capability_string() -> None:
    with pytest.raises(ValidationError):
        ManagerRequest.model_validate(
            {"request_id": "req-1", "goal": "goal", "available_capabilities": ["telekinesis"]}
        )


def test_manager_request_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ManagerRequest.model_validate(
            {"request_id": "req-1", "goal": "goal", "hidden_reasoning": "leak"}
        )


def test_manager_recovery_context_requires_positive_attempt_number() -> None:
    with pytest.raises(ValidationError):
        ManagerRecoveryContext(attempt_number=0)


def test_manager_recovery_context_valid() -> None:
    context = ManagerRecoveryContext(
        attempt_number=2,
        previous_verification_status=VerificationStatus.FAILED,
        previously_excluded_agent_types=["claude_code"],
        failure_summary="unit tests failed",
    )
    request = ManagerRequest(request_id="req-1", goal="goal", recovery_context=context)
    assert request.recovery_context is not None
    assert request.recovery_context.attempt_number == 2


# --- ManagerTaskProposal / ManagerResponse structural bounds ---------------


def test_manager_task_proposal_rejects_blank_description() -> None:
    with pytest.raises(ValidationError):
        ManagerTaskProposal(key="t1", description="   ")


def test_manager_task_proposal_rejects_self_dependency() -> None:
    with pytest.raises(ValidationError):
        ManagerTaskProposal(key="t1", description="do it", depends_on=["t1"])


def test_manager_task_proposal_rejects_duplicate_dependencies() -> None:
    with pytest.raises(ValidationError):
        ManagerTaskProposal(key="t1", description="do it", depends_on=["t2", "t2"])


def test_manager_task_proposal_rejects_unknown_verification_strategy() -> None:
    with pytest.raises(ValidationError):
        ManagerTaskProposal.model_validate(
            {"key": "t1", "description": "do it", "verification_strategy": "vibes_check"}
        )


def test_manager_task_proposal_accepts_known_verification_strategy() -> None:
    task = _task("t1", verification_strategy=BenchmarkEvaluatorType.UNIT_TEST)
    assert task.verification_strategy is BenchmarkEvaluatorType.UNIT_TEST


def test_manager_response_minimal_valid() -> None:
    response = ManagerResponse(request_id="req-1")
    assert response.task_proposals == []
    assert response.clarification_required is False


def test_manager_response_rejects_unique_key_violation() -> None:
    with pytest.raises(ValidationError):
        ManagerResponse(
            request_id="req-1",
            task_proposals=[_task("t1"), _task("t1")],
        )


def test_manager_response_rejects_unknown_dependency_reference() -> None:
    with pytest.raises(ValidationError):
        ManagerResponse(
            request_id="req-1",
            task_proposals=[_task("t1", depends_on=["ghost_task"])],
        )


def test_manager_response_rejects_two_node_cycle() -> None:
    with pytest.raises(ValidationError):
        ManagerResponse(
            request_id="req-1",
            task_proposals=[_task("a", depends_on=["b"]), _task("b", depends_on=["a"])],
        )


def test_manager_response_rejects_three_node_cycle() -> None:
    with pytest.raises(ValidationError):
        ManagerResponse(
            request_id="req-1",
            task_proposals=[
                _task("a", depends_on=["c"]),
                _task("b", depends_on=["a"]),
                _task("c", depends_on=["b"]),
            ],
        )


def test_manager_response_accepts_valid_dag() -> None:
    response = ManagerResponse(
        request_id="req-1",
        task_proposals=[
            _task("a"),
            _task("b", depends_on=["a"]),
            _task("c", depends_on=["a", "b"]),
        ],
    )
    assert [t.key for t in response.task_proposals] == ["a", "b", "c"]


def test_manager_response_rejects_oversized_task_proposals() -> None:
    tasks = [_task(f"t{i}") for i in range(MAX_TASK_PROPOSALS + 1)]
    with pytest.raises(ValidationError):
        ManagerResponse(request_id="req-1", task_proposals=tasks)


def test_manager_response_rejects_oversized_warnings() -> None:
    with pytest.raises(ValidationError):
        ManagerResponse(request_id="req-1", warnings=[f"warn-{i}" for i in range(11)])


def test_manager_response_rejects_oversized_evidence_summary() -> None:
    items = [ManagerEvidenceRef(kind="k", description="d") for _ in range(11)]
    with pytest.raises(ValidationError):
        ManagerResponse(request_id="req-1", evidence_summary=items)


def test_manager_response_rejects_out_of_bounds_confidence() -> None:
    with pytest.raises(ValidationError):
        ManagerResponse(request_id="req-1", confidence=1.5)


def test_manager_response_clarification_requires_question() -> None:
    with pytest.raises(ValidationError):
        ManagerResponse(request_id="req-1", clarification_required=True)


def test_manager_response_question_requires_clarification_flag() -> None:
    with pytest.raises(ValidationError):
        ManagerResponse(
            request_id="req-1", clarification_required=False, clarification_question="why?"
        )


def test_manager_response_accepts_known_recovery_action() -> None:
    response = ManagerResponse(request_id="req-1", recovery_recommendation=RecoveryAction.REROUTE)
    assert response.recovery_recommendation is RecoveryAction.REROUTE


def test_manager_response_rejects_unknown_recovery_action() -> None:
    with pytest.raises(ValidationError):
        ManagerResponse.model_validate(
            {"request_id": "req-1", "recovery_recommendation": "nuke_it"}
        )


def test_manager_response_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ManagerResponse.model_validate({"request_id": "req-1", "chain_of_thought": "leak"})


def test_manager_evidence_ref_has_no_open_value_field() -> None:
    """`ManagerEvidenceRef` deliberately has no `value: Any` field -- unlike
    `VerificationEvidence`/`EvidenceItem`, there is no place for a reserved
    reasoning-shaped key to hide at all."""
    assert "value" not in ManagerEvidenceRef.model_fields


def test_manager_evidence_ref_rejects_path_like_source() -> None:
    with pytest.raises(ValidationError):
        ManagerEvidenceRef(kind="k", description="d", source="/etc/shadow")


def test_manager_response_has_no_verification_status_field() -> None:
    """Structural guarantee for Stage 8A rule 13: the manager can never
    declare verification passed, because there is no field on this type
    that could express a `VerificationStatus` at all."""
    assert "verification_status" not in ManagerResponse.model_fields
    assert "status" not in ManagerResponse.model_fields


def test_manager_response_has_no_reasoning_trace_field() -> None:
    forbidden = {"reasoning_trace", "chain_of_thought", "scratchpad", "internal_reasoning"}
    assert forbidden.isdisjoint(ManagerResponse.model_fields)
    assert forbidden.isdisjoint(ManagerRequest.model_fields)
