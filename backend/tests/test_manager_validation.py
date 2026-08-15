"""Tests for `app.engine.manager.validation.ManagerProposalValidator`: the
contextual validation layer that needs both a `ManagerRequest` and the
`ManagerResponse` answering it."""

import pytest

from app.contracts.enums import AgentCapability
from app.engine.manager.errors import ManagerProposalRejectedError
from app.engine.manager.models import (
    ManagerRecoveryContext,
    ManagerRequest,
    ManagerResponse,
    ManagerTaskProposal,
)
from app.engine.manager.validation import (
    RECOVERY_RECOMMENDATION_WITHOUT_CONTEXT,
    REQUEST_ID_MISMATCH,
    UNKNOWN_PREFERRED_AGENT_TYPE,
    UNKNOWN_REQUIRED_CAPABILITY,
    ManagerProposalValidator,
)
from app.engine.verification.recovery import RecoveryAction


def _request(**overrides: object) -> ManagerRequest:
    base: dict[str, object] = {"request_id": "req-1", "goal": "goal"}
    base.update(overrides)
    return ManagerRequest.model_validate(base)


def test_accepts_response_with_no_task_proposals() -> None:
    validator = ManagerProposalValidator()
    request = _request()
    response = ManagerResponse(request_id="req-1")
    result = validator.validate(response, request)
    assert result.accepted
    assert result.issues == ()


def test_rejects_request_id_mismatch() -> None:
    validator = ManagerProposalValidator()
    request = _request(request_id="req-1")
    response = ManagerResponse(request_id="req-DIFFERENT")
    result = validator.validate(response, request)
    assert not result.accepted
    assert result.issues[0].code == REQUEST_ID_MISMATCH


def test_accepts_known_preferred_agent_type() -> None:
    validator = ManagerProposalValidator()
    request = _request(available_agent_types=["claude_code", "codex"])
    response = ManagerResponse(
        request_id="req-1",
        task_proposals=[
            ManagerTaskProposal(
                key="t1", description="do it", preferred_agent_types=["claude_code"]
            )
        ],
    )
    result = validator.validate(response, request)
    assert result.accepted


def test_rejects_unknown_preferred_agent_type_fail_closed() -> None:
    """The whole response is rejected -- not just the offending task -- when
    a proposal references an agent type outside `available_agent_types`."""
    validator = ManagerProposalValidator()
    request = _request(available_agent_types=["claude_code"])
    response = ManagerResponse(
        request_id="req-1",
        task_proposals=[
            ManagerTaskProposal(
                key="t1", description="do it", preferred_agent_types=["totally_made_up_agent"]
            )
        ],
    )
    result = validator.validate(response, request)
    assert not result.accepted
    assert any(issue.code == UNKNOWN_PREFERRED_AGENT_TYPE for issue in result.issues)


def test_rejects_capability_outside_available_scope() -> None:
    validator = ManagerProposalValidator()
    request = _request(available_capabilities=[AgentCapability.CODE_GENERATION])
    response = ManagerResponse(
        request_id="req-1",
        task_proposals=[
            ManagerTaskProposal(
                key="t1",
                description="do it",
                required_capabilities=[AgentCapability.SHELL_EXECUTION],
            )
        ],
    )
    result = validator.validate(response, request)
    assert not result.accepted
    assert any(issue.code == UNKNOWN_REQUIRED_CAPABILITY for issue in result.issues)


def test_no_available_capabilities_declared_skips_capability_scope_check() -> None:
    """An empty `available_capabilities` list means the request declared no
    allowlist at all -- distinct from declaring an allowlist that excludes
    everything -- so no capability-scope issue is raised in that case."""
    validator = ManagerProposalValidator()
    request = _request(available_capabilities=[])
    response = ManagerResponse(
        request_id="req-1",
        task_proposals=[
            ManagerTaskProposal(
                key="t1",
                description="do it",
                required_capabilities=[AgentCapability.SHELL_EXECUTION],
            )
        ],
    )
    result = validator.validate(response, request)
    assert result.accepted


def test_rejects_recovery_recommendation_without_recovery_context() -> None:
    validator = ManagerProposalValidator()
    request = _request()  # no recovery_context: this is a fresh request
    response = ManagerResponse(request_id="req-1", recovery_recommendation=RecoveryAction.REROUTE)
    result = validator.validate(response, request)
    assert not result.accepted
    assert any(issue.code == RECOVERY_RECOMMENDATION_WITHOUT_CONTEXT for issue in result.issues)


def test_accepts_recovery_recommendation_with_recovery_context() -> None:
    validator = ManagerProposalValidator()
    request = _request(
        recovery_context=ManagerRecoveryContext(attempt_number=2, failure_summary="tests failed")
    )
    response = ManagerResponse(request_id="req-1", recovery_recommendation=RecoveryAction.REROUTE)
    result = validator.validate(response, request)
    assert result.accepted


def test_validate_or_raise_raises_on_rejection_with_issue_codes() -> None:
    validator = ManagerProposalValidator()
    request = _request(available_agent_types=[])
    response = ManagerResponse(
        request_id="req-1",
        task_proposals=[
            ManagerTaskProposal(key="t1", description="do it", preferred_agent_types=["ghost"])
        ],
    )
    with pytest.raises(ManagerProposalRejectedError) as excinfo:
        validator.validate_or_raise(response, request)
    assert UNKNOWN_PREFERRED_AGENT_TYPE in excinfo.value.issues


def test_validate_or_raise_returns_response_on_acceptance() -> None:
    validator = ManagerProposalValidator()
    request = _request()
    response = ManagerResponse(request_id="req-1")
    assert validator.validate_or_raise(response, request) is response


def test_validate_is_deterministic() -> None:
    validator = ManagerProposalValidator()
    request = _request(available_agent_types=["claude_code"])
    response = ManagerResponse(
        request_id="req-1",
        task_proposals=[
            ManagerTaskProposal(key="t1", description="do it", preferred_agent_types=["ghost"])
        ],
    )
    results = [validator.validate(response, request) for _ in range(10)]
    assert all(r == results[0] for r in results)
