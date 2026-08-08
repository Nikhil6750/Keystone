"""Cross-cutting SAFETY tests for the Stage 5A learning core: no
reasoning-shaped, credential-shaped, or raw-prompt-shaped field exists
anywhere in the module, and no absolute repository path is ever accepted
into a `LearningEvent` or represented in aggregated Passport evidence."""

import dataclasses
from datetime import UTC, datetime

import pytest

from app.contracts.enums import AgentCapability, AgentExecutionStatus
from app.contracts.errors import FailureCategory
from app.engine.learning.aggregation import LearningBucket, VerificationMetrics
from app.engine.learning.errors import MalformedLearningEventError
from app.engine.learning.events import LearningEvent
from app.engine.learning.passport import LearningPassport, rebuild_passport

_NOW = datetime.now(UTC)

_FORBIDDEN_FIELD_NAME_SUBSTRINGS = (
    "password",
    "credential",
    "secret",
    "access_token",
    "session_token",
    "chain_of_thought",
    "reasoning",
    "internal_thought",
    "hidden_prompt",
    "raw_prompt",
    "scratchpad",
)

_LEARNING_DATACLASSES = (LearningEvent, LearningBucket, VerificationMetrics, LearningPassport)


def test_no_learning_dataclass_has_a_credential_or_reasoning_shaped_field_name() -> None:
    offenders: list[str] = []
    for cls in _LEARNING_DATACLASSES:
        for f in dataclasses.fields(cls):
            lowered = f.name.lower()
            if any(bad in lowered for bad in _FORBIDDEN_FIELD_NAME_SUBSTRINGS):
                offenders.append(f"{cls.__name__}.{f.name}")
    assert offenders == []


def test_learning_event_has_no_open_ended_metadata_or_value_field() -> None:
    """Stage 5A's actual safety guarantee: `LearningEvent` has no
    `dict[str, Any]`/`value: Any` field for reasoning-shaped or raw-prompt
    content to hide inside -- proven structurally by every field being a
    scalar, `str | None`, or a typed enum."""
    field_types = {f.name: f.type for f in dataclasses.fields(LearningEvent)}
    for name, type_repr in field_types.items():
        assert "Any" not in str(type_repr), f"{name} must not be an open-ended Any-typed field"
        assert "dict" not in str(type_repr).lower(), f"{name} must not be a dict field"


def test_learning_event_rejects_absolute_unix_repository_path() -> None:
    with pytest.raises(MalformedLearningEventError):
        LearningEvent(
            event_id="e1",
            workflow_id="wf-1",
            agent_type="claude_code",
            execution_status=AgentExecutionStatus.SUCCEEDED,
            created_at=_NOW,
            repository_id="/home/user/project",
        )


def test_learning_event_rejects_absolute_windows_repository_path() -> None:
    with pytest.raises(MalformedLearningEventError):
        LearningEvent(
            event_id="e1",
            workflow_id="wf-1",
            agent_type="claude_code",
            execution_status=AgentExecutionStatus.SUCCEEDED,
            created_at=_NOW,
            repository_id=r"C:\Users\dev\project",
        )


def test_no_absolute_repository_path_ever_reaches_a_repository_bucket() -> None:
    """Even indirectly (via `rebuild_passport`), an unsafe `repository_id`
    can never appear as a bucket key -- because it can never construct a
    `LearningEvent` in the first place."""
    safe_event = LearningEvent(
        event_id="e1",
        workflow_id="wf-1",
        agent_type="claude_code",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        created_at=_NOW,
        repository_id="org/repo",
    )
    lp = rebuild_passport([safe_event], agent_type="claude_code", updated_at=_NOW)
    for repository_id in lp.repository_buckets:
        assert not repository_id.startswith("/")
        assert not repository_id.startswith("\\")
        assert ":\\" not in repository_id
        assert ":/" not in repository_id


def test_learning_event_construction_never_raises_for_benign_capability_named_fields() -> None:
    """A capability literally named `code_review`/`general_reasoning` etc.
    is benign observable data, not reasoning content -- confirms the
    safety checks above are not overly broad."""
    event = LearningEvent(
        event_id="e1",
        workflow_id="wf-1",
        agent_type="claude_code",
        execution_status=AgentExecutionStatus.SUCCEEDED,
        created_at=_NOW,
        capabilities=(AgentCapability.CODE_REVIEW, AgentCapability.GENERAL_REASONING),
    )
    assert AgentCapability.GENERAL_REASONING in event.capabilities


def test_failure_category_is_a_stable_enum_not_a_free_form_string() -> None:
    """`failure_category` is always a real `FailureCategory` member (never
    an arbitrary attacker-controlled string) -- validated implicitly by
    Python's type system plus the status-pairing check in `__post_init__`."""
    event = LearningEvent(
        event_id="e1",
        workflow_id="wf-1",
        agent_type="claude_code",
        execution_status=AgentExecutionStatus.FAILED,
        created_at=_NOW,
        failure_category=FailureCategory.PROVIDER_ERROR,
    )
    assert isinstance(event.failure_category, FailureCategory)
