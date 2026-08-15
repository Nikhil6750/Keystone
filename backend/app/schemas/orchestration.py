"""Stage 8C.2 public API schemas for the orchestration execution endpoints.

Reuses Stage 8C.1's own contract types directly (`RepositoryMetadata`,
`RoutingConstraints`, `AgentCapability`) rather than inventing a second,
parallel business schema -- `OrchestrationExecutionCreate` maps field-for-
field onto `app.engine.orchestration.models.OrchestrationRequest` (minus
`recovery_context`, which is a server-driven recovery concept, never a
client-supplied one at creation time).

**Bounded and safe by construction.** Every field here is `extra="forbid"`
and typed -- there is no field through which a client could supply
arbitrary executable code, a shell command, an API key, a provider
`Authorization` header, a raw Manager prompt, or an arbitrary runtime
object. Agent identifiers (`available_agent_types`) are always plain
strings: this schema places no enum or fixed-vocabulary constraint on
agent identity, so any dynamically registered agent ID (`"deepseek-
reviewer"`, `"my-openrouter-qwen-agent"`, ...) is exactly as valid as any
agent ID this codebase ships a built-in adapter for.
"""

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.adapters.workspace import WorkspaceValidationError, validate_workspace_root
from app.contracts.adapter import RepositoryMetadata
from app.contracts.enums import AgentCapability
from app.contracts.routing import RoutingConstraints
from app.contracts.verification import VerificationStatus
from app.engine.manager.models import (
    MAX_AVAILABLE_AGENT_TYPES,
    MAX_AVAILABLE_CAPABILITIES,
    MAX_GOAL_LENGTH,
    MAX_IDENTIFIER_LENGTH,
    MAX_TASK_TYPE_LENGTH,
)
from app.engine.orchestration.events import OrchestrationEventType
from app.engine.orchestration.execution import OrchestrationExecutionStatus
from app.engine.orchestration.models import OrchestrationOutcome
from app.models.enums import WorkflowStatus

_SAFE_EXECUTION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~-]*$")


class OrchestrationExecutionCreate(BaseModel):
    """Client-supplied data to start one orchestration execution."""

    model_config = ConfigDict(extra="forbid")

    goal: str
    task_type: str | None = None
    repository: RepositoryMetadata | None = None
    request_id: str | None = None
    routing_constraints: RoutingConstraints | None = None
    knowledge_query: str | None = None
    available_agent_types: list[str] = Field(default_factory=list)
    available_capabilities: list[AgentCapability] = Field(default_factory=list)
    # The client's own currently open project folder (Stage 8C.3), e.g.
    # `vscode.workspace.workspaceFolders[0]` -- the only source a real
    # local-CLI agent step's subprocess cwd ever comes from. Re-validated
    # (absolute, exists, is a directory) by `OrchestrationRequest`'s own
    # field validator, in addition to being checked here before the route
    # schedules any work.
    workspace_root: str | None = None

    @field_validator("goal")
    @classmethod
    def _goal_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("goal must not be empty")
        if len(value) > MAX_GOAL_LENGTH:
            raise ValueError(f"goal must not exceed {MAX_GOAL_LENGTH} characters")
        return value

    @field_validator("task_type")
    @classmethod
    def _task_type_bounded(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not value.strip():
            raise ValueError("task_type must not be blank if provided")
        if len(value) > MAX_TASK_TYPE_LENGTH:
            raise ValueError(f"task_type must not exceed {MAX_TASK_TYPE_LENGTH} characters")
        return value

    @field_validator("request_id")
    @classmethod
    def _request_id_not_blank_if_given(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not value.strip():
            raise ValueError("request_id must not be blank if provided")
        if len(value) > MAX_IDENTIFIER_LENGTH:
            raise ValueError(f"request_id must not exceed {MAX_IDENTIFIER_LENGTH} characters")
        if _SAFE_EXECUTION_ID_RE.fullmatch(value) is None:
            raise ValueError("request_id must be a URL-safe execution identifier")
        return value

    @field_validator("available_agent_types")
    @classmethod
    def _agent_types_not_blank(cls, value: list[str]) -> list[str]:
        if len(value) > MAX_AVAILABLE_AGENT_TYPES:
            raise ValueError(
                "available_agent_types must not contain more than "
                f"{MAX_AVAILABLE_AGENT_TYPES} entries"
            )
        if any(not entry.strip() for entry in value):
            raise ValueError("available_agent_types entries must not be blank")
        if any(len(entry) > MAX_IDENTIFIER_LENGTH for entry in value):
            raise ValueError(
                f"available_agent_types entries must not exceed {MAX_IDENTIFIER_LENGTH} characters"
            )
        if len(set(value)) != len(value):
            raise ValueError("available_agent_types must not contain duplicates")
        return value

    @field_validator("available_capabilities")
    @classmethod
    def _capabilities_bounded(cls, value: list[AgentCapability]) -> list[AgentCapability]:
        if len(value) > MAX_AVAILABLE_CAPABILITIES:
            raise ValueError(
                "available_capabilities must not contain more than "
                f"{MAX_AVAILABLE_CAPABILITIES} entries"
            )
        if len(set(value)) != len(value):
            raise ValueError("available_capabilities must not contain duplicates")
        return value

    @field_validator("knowledge_query")
    @classmethod
    def _knowledge_query_bounded(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not value.strip():
            raise ValueError("knowledge_query must not be blank if provided")
        if len(value) > MAX_GOAL_LENGTH:
            raise ValueError(f"knowledge_query must not exceed {MAX_GOAL_LENGTH} characters")
        return value

    @field_validator("workspace_root")
    @classmethod
    def _workspace_root_valid(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            return validate_workspace_root(value)
        except WorkspaceValidationError as exc:
            raise ValueError(str(exc)) from exc

    @model_validator(mode="after")
    def _nested_collections_bounded(self) -> "OrchestrationExecutionCreate":
        if self.repository is not None:
            identifiers = (
                self.repository.repository_id,
                self.repository.name,
                self.repository.default_branch,
                self.repository.commit_sha,
            )
            if any(
                value is not None and len(value) > MAX_IDENTIFIER_LENGTH for value in identifiers
            ):
                raise ValueError(
                    f"repository identifiers must not exceed {MAX_IDENTIFIER_LENGTH} characters"
                )
            if len(self.repository.languages) > MAX_AVAILABLE_AGENT_TYPES:
                raise ValueError(
                    "repository.languages must not contain more than "
                    f"{MAX_AVAILABLE_AGENT_TYPES} entries"
                )
            if any(len(value) > MAX_TASK_TYPE_LENGTH for value in self.repository.languages):
                raise ValueError(
                    "repository.languages entries must not exceed "
                    f"{MAX_TASK_TYPE_LENGTH} characters"
                )

        if self.routing_constraints is not None:
            for field_name in (
                "required_capabilities",
                "excluded_agent_types",
                "preferred_agent_types",
            ):
                entries = getattr(self.routing_constraints, field_name)
                if len(entries) > MAX_AVAILABLE_AGENT_TYPES:
                    raise ValueError(
                        f"routing_constraints.{field_name} must not contain more than "
                        f"{MAX_AVAILABLE_AGENT_TYPES} entries"
                    )
                if any(len(value) > MAX_IDENTIFIER_LENGTH for value in entries):
                    raise ValueError(
                        f"routing_constraints.{field_name} entries must not exceed "
                        f"{MAX_IDENTIFIER_LENGTH} characters"
                    )
        return self


class OrchestrationExecutionAccepted(BaseModel):
    """`202 Accepted` response body for `POST /orchestrations`."""

    model_config = ConfigDict(from_attributes=True)

    execution_id: str
    status: OrchestrationExecutionStatus
    events_url: str
    result_url: str


class OrchestrationExecutionRead(BaseModel):
    """Safe, observable execution state for `GET /orchestrations/{execution_id}`.

    `job_status` (transport/job lifecycle) and `orchestration_outcome`
    (business result) are deliberately separate fields, never collapsed --
    see `app.engine.orchestration.execution`'s module docstring. Every
    other field mirrors `OrchestrationResult`'s own already-certified-safe
    field set; nothing here is derived from raw provider output.
    """

    model_config = ConfigDict(from_attributes=True)

    execution_id: str
    job_status: OrchestrationExecutionStatus
    orchestration_outcome: OrchestrationOutcome | None = None
    workflow_id: str | None = None
    final_workflow_state: WorkflowStatus | None = None
    verification_status: VerificationStatus | None = None
    task_count: int | None = None
    selected_agent_types: tuple[str, ...] = ()
    attempt_count: int | None = None
    recovery_used: bool | None = None
    recovery_action: str | None = None
    learning_event_count: int | None = None
    retrieval_feedback_recorded: bool | None = None
    issue_codes: tuple[str, ...] = ()
    quality_run_id: str | None = None
    quality_verdict_status: str | None = None
    error_summary: str | None = None
    created_at: datetime
    updated_at: datetime


class OrchestrationEventRead(BaseModel):
    """Serialized shape of one `OrchestrationEvent` for the SSE `data:`
    payload -- mirrors the dataclass field-for-field; see
    `app.engine.orchestration.events` for the security guarantees this
    already carries (no CoT/raw provider output/secrets, ever)."""

    model_config = ConfigDict(from_attributes=True)

    event_id: str
    execution_id: str
    sequence: int
    event_type: OrchestrationEventType
    timestamp: datetime
    phase: str | None = None
    status: str | None = None
    workflow_id: str | None = None
    task_key: str | None = None
    agent_id: str | None = None
    attempt_number: int | None = None
    verification_status: str | None = None
    safe_issue_codes: tuple[str, ...] = ()
    message: str | None = None


def orchestration_execution_create_to_kwargs(data: OrchestrationExecutionCreate) -> dict[str, Any]:
    """Maps the public request onto `OrchestrationRequest`'s constructor
    kwargs -- `request_id` is handled by the caller (generated if the
    client omitted it), never here, so this function stays a pure,
    total mapping of the fields this schema actually declares."""
    return {
        "goal": data.goal,
        "task_type": data.task_type,
        "repository": data.repository,
        "available_agent_types": list(data.available_agent_types),
        "available_capabilities": list(data.available_capabilities),
        "routing_constraints": data.routing_constraints or RoutingConstraints(),
        "knowledge_query": data.knowledge_query,
        "workspace_root": data.workspace_root,
    }


__all__ = [
    "OrchestrationEventRead",
    "OrchestrationExecutionAccepted",
    "OrchestrationExecutionCreate",
    "OrchestrationExecutionRead",
    "orchestration_execution_create_to_kwargs",
]
