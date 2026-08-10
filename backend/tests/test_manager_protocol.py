"""Tests for `app.engine.manager.protocol`: the `ManagerModel` Protocol
shape and `parse_manager_response`'s typed-error conversion."""

import pytest

from app.engine.manager.errors import ManagerInvalidResponseError
from app.engine.manager.fake import FakeManagerModel
from app.engine.manager.models import ManagerResponse
from app.engine.manager.protocol import ManagerModel, parse_manager_response


def test_fake_manager_model_satisfies_the_protocol() -> None:
    """`ManagerModel` is a plain (non-`runtime_checkable`) `Protocol`,
    matching `app.contracts.adapter.AgentAdapter`'s own convention --
    structural conformance is checked by attribute shape, not `isinstance`."""
    fake = FakeManagerModel(response=ManagerResponse(request_id="req-1"))
    assert hasattr(fake, "identifier") and callable(fake.identifier)
    assert hasattr(fake, "propose") and callable(fake.propose)
    assert hasattr(ManagerModel, "identifier")
    assert hasattr(ManagerModel, "propose")


def test_parse_manager_response_accepts_well_formed_payload() -> None:
    parsed = parse_manager_response({"request_id": "req-1", "goal_interpretation": "build X"})
    assert isinstance(parsed, ManagerResponse)
    assert parsed.request_id == "req-1"


def test_parse_manager_response_rejects_malformed_payload() -> None:
    with pytest.raises(ManagerInvalidResponseError):
        parse_manager_response({"request_id": "req-1", "confidence": 5.0})


def test_parse_manager_response_rejects_unknown_extra_field() -> None:
    with pytest.raises(ManagerInvalidResponseError):
        parse_manager_response({"request_id": "req-1", "chain_of_thought": "leak"})


def test_parse_manager_response_error_never_echoes_raw_payload() -> None:
    """The typed error message must summarize, not forward, a potentially
    untrusted provider payload verbatim."""
    secret_marker = "super-secret-payload-marker-should-not-leak"
    with pytest.raises(ManagerInvalidResponseError) as excinfo:
        parse_manager_response({"request_id": secret_marker, "confidence": 99.0})
    assert secret_marker not in str(excinfo.value)


def test_parse_manager_response_rejects_cyclic_task_proposals() -> None:
    with pytest.raises(ManagerInvalidResponseError):
        parse_manager_response(
            {
                "request_id": "req-1",
                "task_proposals": [
                    {"key": "a", "description": "do a", "depends_on": ["b"]},
                    {"key": "b", "description": "do b", "depends_on": ["a"]},
                ],
            }
        )
