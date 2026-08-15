"""Provider-neutral agent adapter contract.

This is the vNext, asynchronous contract Developer 3's connectors will
implement. It is deliberately separate from the existing synchronous
`AgentExecutor` protocol (`app.engine.executor`), which the live
`WorkflowEngine` calls today and which this stage does not modify — later
stages bridge or migrate execution onto `AgentAdapter` incrementally.

Provider-specific detail (raw CLI flags, provider request IDs, model
parameters, etc.) belongs in the optional `metadata` field on the request and
result, never as a first-class field here, so this contract stays stable as
new providers are added.
"""

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts.enums import AgentCapability, AgentExecutionStatus, AgentStatus, RuntimeKind
from app.contracts.errors import FailureCategory


class RepositoryMetadata(BaseModel):
    """Non-sensitive repository context passed to an agent execution.

    Never carries an absolute filesystem path or credentials — only
    identifying and descriptive metadata a routing/passport signal or a
    provider prompt might use.
    """

    model_config = ConfigDict(extra="forbid")

    repository_id: str | None = None
    name: str | None = None
    default_branch: str | None = None
    commit_sha: str | None = None
    languages: list[str] = Field(default_factory=list)


class AgentUsage(BaseModel):
    """Optional token/cost usage, populated only when a provider reports it."""

    model_config = ConfigDict(extra="forbid")

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None


class AgentDescriptor(BaseModel):
    """Static identity and capability declaration for one registered agent.

    `runtime_kind` defaults to `AGENT_CLI` — every currently-implemented
    connector (Claude Code, Codex, Antigravity, Gemini, the demo adapter) is
    an autonomous CLI, so this default reflects today's reality without
    requiring any existing caller to change. A model-API/local-model/hybrid
    runtime sets it explicitly.
    """

    model_config = ConfigDict(from_attributes=True)

    agent_type: str
    display_name: str
    runtime_kind: RuntimeKind = RuntimeKind.AGENT_CLI
    capabilities: list[AgentCapability] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentExecutionRequest(BaseModel):
    """Everything an `AgentAdapter.execute()` call needs, provider-agnostic."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    agent_type: str
    execution_id: str
    workflow_id: str
    step_id: str
    task_type: str
    repository: RepositoryMetadata | None = None
    input_payload: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float
    attempt_number: int = 1
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _positive_bounds(self) -> "AgentExecutionRequest":
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.attempt_number < 1:
            raise ValueError("attempt_number must be at least 1")
        return self


class AgentExecutionResult(BaseModel):
    """The outcome of one `AgentAdapter.execute()` call, provider-agnostic."""

    model_config = ConfigDict(from_attributes=True)

    agent_id: str
    agent_type: str
    execution_id: str
    workflow_id: str
    step_id: str
    status: AgentExecutionStatus
    output_payload: dict[str, Any] | None = None
    failure_category: FailureCategory | None = None
    error_message: str | None = None
    duration_ms: float | None = None
    attempt_number: int = 1
    usage: AgentUsage | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _status_failure_category_consistency(self) -> "AgentExecutionResult":
        """Enforce the exact `status` <-> `failure_category` pairing. Never
        rewrites the input to make it consistent — an inconsistent
        combination is a caller bug and must fail loudly."""
        if self.status is AgentExecutionStatus.SUCCEEDED and self.failure_category is not None:
            raise ValueError("failure_category must be None when status is SUCCEEDED")
        if self.status is AgentExecutionStatus.FAILED and self.failure_category is None:
            raise ValueError("failure_category is required when status is FAILED")
        if (
            self.status is AgentExecutionStatus.CANCELLED
            and self.failure_category is not FailureCategory.CANCELLED
        ):
            raise ValueError("failure_category must be CANCELLED when status is CANCELLED")
        if (
            self.status is AgentExecutionStatus.TIMED_OUT
            and self.failure_category is not FailureCategory.TIMEOUT
        ):
            raise ValueError("failure_category must be TIMEOUT when status is TIMED_OUT")
        return self


class AgentAdapter(Protocol):
    """One provider connector, implemented by Developer 3's connector modules.

    `describe()` and `capabilities()` are synchronous (pure metadata, no I/O);
    `verify()`, `health()`, `execute()` and `cancel()` are asynchronous since
    they may perform process or network I/O.
    """

    def describe(self) -> AgentDescriptor:
        """Return this adapter's static identity and capability declaration."""
        ...

    def capabilities(self) -> list[AgentCapability]:
        """Return the capability tags this adapter supports."""
        ...

    async def verify(self) -> AgentStatus:
        """Check installation/authentication and return an aggregate readiness signal."""
        ...

    async def health(self) -> AgentStatus:
        """Return a lightweight, frequently-pollable readiness signal."""
        ...

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        """Run one step against this agent and return its structured result."""
        ...

    async def cancel(self, execution_id: str) -> bool:
        """Best-effort cancellation of an in-flight execution.

        Returns `True` if cancellation was accepted (the execution may still
        take a moment to actually stop), `False` if `execution_id` is unknown
        or already finished.
        """
        ...


__all__ = [
    "AgentAdapter",
    "AgentDescriptor",
    "AgentExecutionRequest",
    "AgentExecutionResult",
    "AgentUsage",
    "RepositoryMetadata",
]
