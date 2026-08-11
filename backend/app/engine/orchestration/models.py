"""Stage 8C.1 orchestration request/result contracts.

`OrchestrationRequest` is the single bounded input `EndToEndOrchestrationService
.orchestrate()` accepts, expressing one developer goal. It deliberately
reuses existing typed models wherever one already exists instead of
duplicating their shape: `RepositoryMetadata` (`app.contracts.adapter`),
`AgentCapability` (`app.contracts.enums`), `RoutingConstraints`
(`app.contracts.routing`), and `ManagerRecoveryContext`
(`app.engine.manager.models`) are all used verbatim. Bound constants
(`MAX_GOAL_LENGTH`, `MAX_IDENTIFIER_LENGTH`) are imported from
`app.engine.manager.models` rather than redefined, since a goal ultimately
flows into a `ManagerRequest` built from the same fields and must satisfy
the same bounds either way.

`OrchestrationResult` is a frozen dataclass (matching `ManagerOrchestrationResult`'s
own precedent, `app.engine.manager.orchestrator`) exposing only safe,
observable facts -- references, counts, and status enums, never raw model
output, prompts, or provider bodies. `OrchestrationOutcome` names every
deterministic terminal state the pipeline can reach; each one is a normal,
expected result, not an exception (see `errors.py`'s module docstring for
why).
"""

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.adapters.workspace import WorkspaceValidationError, validate_workspace_root
from app.contracts.adapter import RepositoryMetadata
from app.contracts.enums import AgentCapability
from app.contracts.routing import RoutingConstraints
from app.contracts.verification import VerificationStatus
from app.engine.manager.models import (
    MAX_GOAL_LENGTH,
    MAX_IDENTIFIER_LENGTH,
    ManagerRecoveryContext,
)
from app.engine.verification.recovery import RecoveryAction
from app.models.enums import WorkflowStatus


def _not_blank(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value


class OrchestrationRequest(BaseModel):
    """One bounded, provider-neutral request to run a developer goal
    through the full Keystone pipeline. Contains only what the wired
    subsystems actually need -- no raw secrets, credentials, or unbounded
    collections (the same discipline `ManagerRequest` already enforces for
    the fields this type shares with it). `workspace_root` is the one
    deliberate exception to "no absolute filesystem paths": a real local-
    CLI agent step needs *some* directory to actually work in (Stage
    8C.3), and this is the only source for it -- an executor's subprocess
    cwd is never derived from `goal` or any other free-text field."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    goal: str
    task_type: str | None = None
    repository: RepositoryMetadata | None = None
    available_agent_types: list[str] = Field(default_factory=list)
    available_capabilities: list[AgentCapability] = Field(default_factory=list)
    routing_constraints: RoutingConstraints = Field(default_factory=RoutingConstraints)
    recovery_context: ManagerRecoveryContext | None = None
    knowledge_query: str | None = None
    workspace_root: str | None = None

    @field_validator("request_id")
    @classmethod
    def _request_id_valid(cls, value: str) -> str:
        _not_blank(value, "request_id")
        if len(value) > MAX_IDENTIFIER_LENGTH:
            raise ValueError(f"request_id must not exceed {MAX_IDENTIFIER_LENGTH} characters")
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

    @field_validator("goal")
    @classmethod
    def _goal_valid(cls, value: str) -> str:
        _not_blank(value, "goal")
        if len(value) > MAX_GOAL_LENGTH:
            raise ValueError(f"goal must not exceed {MAX_GOAL_LENGTH} characters")
        return value

    @field_validator("knowledge_query")
    @classmethod
    def _knowledge_query_valid(cls, value: str | None) -> str | None:
        if value is None:
            return value
        _not_blank(value, "knowledge_query")
        if len(value) > MAX_GOAL_LENGTH:
            raise ValueError(f"knowledge_query must not exceed {MAX_GOAL_LENGTH} characters")
        return value


class OrchestrationOutcome(StrEnum):
    """Every deterministic terminal state one `orchestrate()` call can
    reach. Each value is a normal, expected result -- see `errors.py`'s
    module docstring for why these are result values, not exceptions."""

    VERIFIED_SUCCESS = "verified_success"
    VERIFICATION_FAILED = "verification_failed"
    RUNTIME_FAILURE = "runtime_failure"
    NO_ELIGIBLE_ROUTE = "no_eligible_route"
    RECOVERY_EXHAUSTED = "recovery_exhausted"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class OrchestrationResult:
    """Observable outcome of one full orchestration pass -- safe facts
    only. Never carries hidden chain-of-thought, `reasoning_content`, raw
    model/provider output, credentials, unrestricted prompts, arbitrary
    stack traces, or unbounded agent stdout/stderr; see `service.py` for
    exactly how each field is derived."""

    request_id: str
    outcome: OrchestrationOutcome
    workflow_id: str | None
    final_workflow_state: WorkflowStatus | None
    task_count: int
    step_count: int
    manager_used: bool
    manager_fallback_used: bool
    manager_proposal_validated: bool | None
    manager_provider_identifier: str | None
    knowledge_result_count: int
    adaptive_retrieval_used: bool
    selected_agent_types: tuple[str, ...] = ()
    attempt_count: int = 0
    verification_status: VerificationStatus | None = None
    recovery_used: bool = False
    recovery_action: RecoveryAction | None = None
    learning_event_ids: tuple[str, ...] = ()
    retrieval_feedback_recorded: bool = False
    warnings: tuple[str, ...] = ()
    issue_codes: tuple[str, ...] = ()


__all__ = ["OrchestrationOutcome", "OrchestrationRequest", "OrchestrationResult"]
