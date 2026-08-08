"""Planning contracts: the Planner's "what work needs to happen" output.

`TaskSpec` deliberately has no `agent_type` field — the Planner decides what
work exists, never who performs it; that is the Router's job
(`app.contracts.routing`). A later "compiler" step combines a `TaskSpec` with
the Router's `RoutingDecision` to produce a `WorkflowStepDefinition`
(`app.contracts.workflow`) the Stage 2 scheduler can actually execute — this
module does not build that compiler, only the shape it consumes.

Cycle detection here is a small, self-contained helper deliberately not
shared with `app.engine.workflow.graph.WorkflowGraph`'s algorithm: contracts
sit below the engine layer in the dependency direction documented in
`docs/contracts.md` and must never import from it. The two implementations
are structurally similar by design (same DFS shape) but independently
defined.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.contracts.adapter import RepositoryMetadata
from app.contracts.enums import AgentCapability, BenchmarkEvaluatorType
from app.contracts.knowledge import KnowledgeSearchResult
from app.contracts.routing import RoutingConstraints


class ExpectedOutcome(BaseModel):
    """What "done" means for one task, for the future Verifier to check
    against the executed step's actual result."""

    model_config = ConfigDict(extra="forbid")

    evaluator_type: BenchmarkEvaluatorType
    criteria: dict[str, Any] = Field(default_factory=dict)
    description: str | None = None

    @field_validator("description")
    @classmethod
    def _description_not_blank_if_present(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("description must not be blank if provided")
        return value


class TaskSpec(BaseModel):
    """One node in a Planner-produced task graph.

    Deliberately has no `agent_type`: only `required_capabilities` and
    `task_type`, which the Router resolves into a concrete agent later. Only
    structural well-formedness (unique keys, known dependencies, no
    self-dependency, no cycles) is validated at the `WorkflowPlan` level,
    mirroring `WorkflowStepDefinition`/`WorkflowDefinition`'s own split.
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    name: str
    task_type: str
    required_capabilities: list[AgentCapability] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    input_payload: dict[str, Any] = Field(default_factory=dict)
    expected_outcome: ExpectedOutcome | None = None

    @field_validator("key", "name", "task_type")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @model_validator(mode="after")
    def _no_self_dependency_or_duplicates(self) -> "TaskSpec":
        if self.key in self.depends_on:
            raise ValueError(f"task '{self.key}' cannot depend on itself")
        if len(self.depends_on) != len(set(self.depends_on)):
            raise ValueError(f"task '{self.key}' has duplicate entries in depends_on")
        return self


class WorkflowPlan(BaseModel):
    """A Planner's full output: an ordered, dependency-linked task graph for
    one goal. List order is preserved exactly as given — task ordering is
    deterministic by construction, not recomputed here."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str
    goal: str
    tasks: list[TaskSpec] = Field(default_factory=list)
    repository: RepositoryMetadata | None = None
    # Non-sensitive only: see docs/contracts.md's "Allowed metadata and
    # provenance content" — no credentials, tokens, or private file content.
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    @field_validator("plan_id", "goal")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @model_validator(mode="after")
    def _unique_keys_known_dependencies_no_cycles(self) -> "WorkflowPlan":
        keys = [task.key for task in self.tasks]
        if len(keys) != len(set(keys)):
            raise ValueError("task keys must be unique within a plan")
        known = set(keys)
        for task in self.tasks:
            unknown = [dep for dep in task.depends_on if dep not in known]
            if unknown:
                raise ValueError(
                    f"task '{task.key}' depends on undeclared task(s): {', '.join(unknown)}"
                )

        cycle = _detect_cycle({task.key: task for task in self.tasks})
        if cycle is not None:
            raise ValueError(f"workflow plan contains a cycle: {' -> '.join(cycle)}")
        return self


class PlanningRequest(BaseModel):
    """A request for the Planner to decompose one goal into a `WorkflowPlan`."""

    model_config = ConfigDict(extra="forbid")

    goal: str
    repository: RepositoryMetadata | None = None
    constraints: RoutingConstraints = Field(default_factory=RoutingConstraints)
    available_capabilities: list[AgentCapability] = Field(default_factory=list)
    knowledge_context: list[KnowledgeSearchResult] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("goal")
    @classmethod
    def _goal_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("goal must not be empty")
        return value


def _detect_cycle(tasks: dict[str, TaskSpec]) -> list[str] | None:
    visiting: set[str] = set()
    visited: set[str] = set()
    path: list[str] = []

    def visit(key: str) -> list[str] | None:
        if key in visiting:
            cycle_start = path.index(key)
            return [*path[cycle_start:], key]
        if key in visited:
            return None
        visiting.add(key)
        path.append(key)
        for dependency in tasks[key].depends_on:
            result = visit(dependency)
            if result is not None:
                return result
        path.pop()
        visiting.discard(key)
        visited.add(key)
        return None

    for key in tasks:
        if key not in visited:
            found = visit(key)
            if found is not None:
                return found
    return None


__all__ = ["ExpectedOutcome", "PlanningRequest", "TaskSpec", "WorkflowPlan"]
