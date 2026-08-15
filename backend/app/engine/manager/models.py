"""Provider-neutral manager request/response contracts for Stage 8A.

`ManagerRequest` is the bounded, non-sensitive input a `ManagerModel`
(`protocol.py`) receives; `ManagerResponse` is the structured proposal it
returns. Both are Pydantic models (`extra="forbid"`, matching every contract
in `app.contracts`) with defensive, centrally-defined bounds -- an oversized
or malformed response cannot even be constructed, let alone reach
orchestration. This is the first of two validation layers: the second,
contextual layer (known agent types/capabilities *for this specific
request*, request/response correlation) lives in `validation.py`, since it
needs both objects together.

**No chain-of-thought, structurally.** Neither model has a `reasoning_trace`/
`chain_of_thought`/`scratchpad`/`internal_reasoning` field, and neither has
an open `value: Any` field a provider could smuggle one into (unlike
`VerificationEvidence`/`EvidenceItem`, which need such a field for arbitrary
observed values and so defend it at runtime via
`app.contracts.evidence_safety`, this package's evidence type
(`ManagerEvidenceRef`) has no `value` field at all -- the safety property
holds by construction, not by a runtime key check).

**No verification/recovery authority.** `ManagerResponse` has no field that
could express "verification passed" (only a *requested* `verification_strategy`,
reusing `BenchmarkEvaluatorType` rather than inventing a parallel taxonomy)
and no field that mutates a learning/passport record. `recovery_recommendation`
reuses `app.engine.verification.recovery.RecoveryAction` verbatim -- Stage
8A never invents a parallel recovery state machine.
"""

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.contracts.enums import AgentCapability, BenchmarkEvaluatorType
from app.contracts.knowledge import KnowledgeSearchResult
from app.contracts.routing import RoutingConstraints
from app.contracts.verification import VerificationStatus
from app.engine.verification.recovery import RecoveryAction

# --- Centrally-defined bounds -------------------------------------------
# Every collection/length bound anywhere in this module is defined exactly
# once here (Stage 8A rule 16: "Place limits centrally"). Pydantic enforces
# these at construction, so a `ManagerRequest`/`ManagerResponse` that
# violates one of them simply cannot be built -- fail closed, not a
# separate runtime check bolted on afterward.

MAX_GOAL_LENGTH = 4000
MAX_TASK_TYPE_LENGTH = 100
MAX_REPOSITORY_ID_LENGTH = 200
MAX_IDENTIFIER_LENGTH = 200
MAX_AVAILABLE_AGENT_TYPES = 50
MAX_AVAILABLE_CAPABILITIES = 30
MAX_KNOWLEDGE_CONTEXT_ITEMS = 20
MAX_EXCLUDED_AGENT_TYPES = 50
MAX_FAILURE_SUMMARY_LENGTH = 500

MAX_TASK_PROPOSALS = 12
MAX_TASK_DESCRIPTION_LENGTH = 500
MAX_DEPENDENCIES_PER_TASK = 8
MAX_PREFERRED_AGENTS_PER_TASK = 5
MAX_CAPABILITIES_PER_TASK = 10

MAX_EVIDENCE_ITEMS = 10
MAX_EVIDENCE_DESCRIPTION_LENGTH = 500
MAX_EVIDENCE_KIND_LENGTH = 100
MAX_EVIDENCE_SOURCE_LENGTH = 200

MAX_WARNINGS = 10
MAX_WARNING_LENGTH = 300
MAX_GOAL_INTERPRETATION_LENGTH = 1000
MAX_CLARIFICATION_QUESTION_LENGTH = 500
MAX_PROVIDER_IDENTIFIER_LENGTH = 100

MAX_KNOWLEDGE_NEEDS = 5
MAX_KNOWLEDGE_QUERY_LENGTH = 200

_ABSOLUTE_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _looks_like_unsafe_path(value: str) -> bool:
    """True if `value` looks like an absolute filesystem path or contains a
    `..` traversal segment, rather than an opaque identifier -- the same
    check `app.engine.learning.events`/`app.engine.adaptive_retrieval.models`
    independently apply to their own identifier fields."""
    if value.startswith("/") or value.startswith("\\"):
        return True
    if _ABSOLUTE_DRIVE_PATH_RE.match(value):
        return True
    segments = re.split(r"[\\/]", value)
    return ".." in segments


def _not_blank(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value


def _bounded_unique_strings(
    value: list[str], field_name: str, *, max_items: int, max_length: int
) -> list[str]:
    if len(value) > max_items:
        raise ValueError(f"{field_name} must not contain more than {max_items} entries")
    for entry in value:
        if not entry.strip():
            raise ValueError(f"{field_name} entries must not be blank")
        if len(entry) > max_length:
            raise ValueError(f"{field_name} entries must not exceed {max_length} characters")
    if len(set(value)) != len(value):
        raise ValueError(f"{field_name} must not contain duplicates")
    return value


class ManagerRecoveryContext(BaseModel):
    """Bounded, observable context about a prior failed attempt -- never a
    parallel recovery state machine, only the same facts
    `app.engine.verification.recovery.RecoveryDecision` already tracks."""

    model_config = ConfigDict(extra="forbid")

    attempt_number: int
    previous_verification_status: VerificationStatus | None = None
    previously_excluded_agent_types: list[str] = Field(default_factory=list)
    failure_summary: str | None = None

    @field_validator("attempt_number")
    @classmethod
    def _attempt_number_valid(cls, value: int) -> int:
        if value < 1:
            raise ValueError("attempt_number must be at least 1")
        return value

    @field_validator("previously_excluded_agent_types")
    @classmethod
    def _excluded_agent_types_bounded(cls, value: list[str]) -> list[str]:
        return _bounded_unique_strings(
            value,
            "previously_excluded_agent_types",
            max_items=MAX_EXCLUDED_AGENT_TYPES,
            max_length=MAX_IDENTIFIER_LENGTH,
        )

    @field_validator("failure_summary")
    @classmethod
    def _failure_summary_bounded(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not value.strip():
            raise ValueError("failure_summary must not be blank if provided")
        if len(value) > MAX_FAILURE_SUMMARY_LENGTH:
            raise ValueError(
                f"failure_summary must not exceed {MAX_FAILURE_SUMMARY_LENGTH} characters"
            )
        return value


class ManagerRequest(BaseModel):
    """A bounded, provider-neutral request for one `ManagerModel.propose()`
    call. Contains only what section 4 of the Stage 8A spec allows: no raw
    secrets, no credentials, no absolute filesystem paths, no database URLs,
    no hidden reasoning, no arbitrary environment variables."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    goal: str
    task_type: str | None = None
    repository_id: str | None = None
    available_agent_types: list[str] = Field(default_factory=list)
    available_capabilities: list[AgentCapability] = Field(default_factory=list)
    knowledge_context: list[KnowledgeSearchResult] = Field(default_factory=list)
    workflow_constraints: RoutingConstraints | None = None
    recovery_context: ManagerRecoveryContext | None = None

    @field_validator("request_id")
    @classmethod
    def _request_id_valid(cls, value: str) -> str:
        _not_blank(value, "request_id")
        if len(value) > MAX_IDENTIFIER_LENGTH:
            raise ValueError(f"request_id must not exceed {MAX_IDENTIFIER_LENGTH} characters")
        return value

    @field_validator("goal")
    @classmethod
    def _goal_valid(cls, value: str) -> str:
        _not_blank(value, "goal")
        if len(value) > MAX_GOAL_LENGTH:
            raise ValueError(f"goal must not exceed {MAX_GOAL_LENGTH} characters")
        return value

    @field_validator("task_type")
    @classmethod
    def _task_type_valid(cls, value: str | None) -> str | None:
        if value is None:
            return value
        _not_blank(value, "task_type")
        if len(value) > MAX_TASK_TYPE_LENGTH:
            raise ValueError(f"task_type must not exceed {MAX_TASK_TYPE_LENGTH} characters")
        return value

    @field_validator("repository_id")
    @classmethod
    def _repository_id_valid(cls, value: str | None) -> str | None:
        if value is None:
            return value
        _not_blank(value, "repository_id")
        if len(value) > MAX_REPOSITORY_ID_LENGTH:
            raise ValueError(f"repository_id must not exceed {MAX_REPOSITORY_ID_LENGTH} characters")
        if _looks_like_unsafe_path(value):
            raise ValueError(
                f"repository_id must not look like an absolute filesystem path: {value!r}"
            )
        return value

    @field_validator("available_agent_types")
    @classmethod
    def _available_agent_types_bounded(cls, value: list[str]) -> list[str]:
        return _bounded_unique_strings(
            value,
            "available_agent_types",
            max_items=MAX_AVAILABLE_AGENT_TYPES,
            max_length=MAX_IDENTIFIER_LENGTH,
        )

    @field_validator("available_capabilities")
    @classmethod
    def _available_capabilities_bounded(cls, value: list[AgentCapability]) -> list[AgentCapability]:
        if len(value) > MAX_AVAILABLE_CAPABILITIES:
            raise ValueError(
                "available_capabilities must not contain more than "
                f"{MAX_AVAILABLE_CAPABILITIES} entries"
            )
        if len(set(value)) != len(value):
            raise ValueError("available_capabilities must not contain duplicates")
        return value

    @field_validator("knowledge_context")
    @classmethod
    def _knowledge_context_bounded(
        cls, value: list[KnowledgeSearchResult]
    ) -> list[KnowledgeSearchResult]:
        if len(value) > MAX_KNOWLEDGE_CONTEXT_ITEMS:
            raise ValueError(
                f"knowledge_context must not contain more than {MAX_KNOWLEDGE_CONTEXT_ITEMS} items"
            )
        return value


class ManagerEvidenceRef(BaseModel):
    """One piece of observable evidence a manager proposal cites -- kind,
    description, source, sample size only. Deliberately has no `value: Any`
    field (unlike `VerificationEvidence`/`EvidenceItem`): there is no place
    for reasoning-shaped content to hide, the same "no open field" guarantee
    `LearningEvent` documents for itself."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    description: str
    source: str | None = None
    sample_size: int | None = None

    @field_validator("kind")
    @classmethod
    def _kind_valid(cls, value: str) -> str:
        _not_blank(value, "kind")
        if len(value) > MAX_EVIDENCE_KIND_LENGTH:
            raise ValueError(f"kind must not exceed {MAX_EVIDENCE_KIND_LENGTH} characters")
        return value

    @field_validator("description")
    @classmethod
    def _description_valid(cls, value: str) -> str:
        _not_blank(value, "description")
        if len(value) > MAX_EVIDENCE_DESCRIPTION_LENGTH:
            raise ValueError(
                f"description must not exceed {MAX_EVIDENCE_DESCRIPTION_LENGTH} characters"
            )
        return value

    @field_validator("source")
    @classmethod
    def _source_valid(cls, value: str | None) -> str | None:
        if value is None:
            return value
        _not_blank(value, "source")
        if len(value) > MAX_EVIDENCE_SOURCE_LENGTH:
            raise ValueError(f"source must not exceed {MAX_EVIDENCE_SOURCE_LENGTH} characters")
        if _looks_like_unsafe_path(value):
            raise ValueError(f"source must not look like an absolute filesystem path: {value!r}")
        return value

    @field_validator("sample_size")
    @classmethod
    def _sample_size_valid(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("sample_size must not be negative")
        return value


class ManagerTaskProposal(BaseModel):
    """One decomposition-hint node the manager proposes. Never authoritative
    on its own -- `ManagerProposalValidator` (`validation.py`) must accept it
    before `ManagerOrchestrator` may fold any part of it into a deterministic
    orchestration input, and even then only `preferred_agent_types` is ever
    used (see `orchestrator.py`); the existing `Planner` always produces the
    actual `WorkflowPlan`."""

    model_config = ConfigDict(extra="forbid")

    key: str
    description: str
    task_type: str | None = None
    required_capabilities: list[AgentCapability] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    preferred_agent_types: list[str] = Field(default_factory=list)
    verification_strategy: BenchmarkEvaluatorType | None = None

    @field_validator("key")
    @classmethod
    def _key_valid(cls, value: str) -> str:
        _not_blank(value, "key")
        if len(value) > MAX_IDENTIFIER_LENGTH:
            raise ValueError(f"key must not exceed {MAX_IDENTIFIER_LENGTH} characters")
        return value

    @field_validator("description")
    @classmethod
    def _description_valid(cls, value: str) -> str:
        _not_blank(value, "description")
        if len(value) > MAX_TASK_DESCRIPTION_LENGTH:
            raise ValueError(
                f"description must not exceed {MAX_TASK_DESCRIPTION_LENGTH} characters"
            )
        return value

    @field_validator("task_type")
    @classmethod
    def _task_type_valid(cls, value: str | None) -> str | None:
        if value is None:
            return value
        _not_blank(value, "task_type")
        if len(value) > MAX_TASK_TYPE_LENGTH:
            raise ValueError(f"task_type must not exceed {MAX_TASK_TYPE_LENGTH} characters")
        return value

    @field_validator("required_capabilities")
    @classmethod
    def _required_capabilities_bounded(cls, value: list[AgentCapability]) -> list[AgentCapability]:
        if len(value) > MAX_CAPABILITIES_PER_TASK:
            raise ValueError(
                "required_capabilities must not contain more than "
                f"{MAX_CAPABILITIES_PER_TASK} entries"
            )
        if len(set(value)) != len(value):
            raise ValueError("required_capabilities must not contain duplicates")
        return value

    @field_validator("depends_on")
    @classmethod
    def _depends_on_bounded(cls, value: list[str]) -> list[str]:
        return _bounded_unique_strings(
            value,
            "depends_on",
            max_items=MAX_DEPENDENCIES_PER_TASK,
            max_length=MAX_IDENTIFIER_LENGTH,
        )

    @field_validator("preferred_agent_types")
    @classmethod
    def _preferred_agent_types_bounded(cls, value: list[str]) -> list[str]:
        return _bounded_unique_strings(
            value,
            "preferred_agent_types",
            max_items=MAX_PREFERRED_AGENTS_PER_TASK,
            max_length=MAX_IDENTIFIER_LENGTH,
        )

    @model_validator(mode="after")
    def _no_self_dependency(self) -> "ManagerTaskProposal":
        if self.key in self.depends_on:
            raise ValueError(f"task '{self.key}' cannot depend on itself")
        return self


def _detect_cycle(tasks: dict[str, ManagerTaskProposal]) -> list[str] | None:
    """Independent DFS cycle detector for `ManagerResponse.task_proposals`.

    Deliberately not shared with `app.contracts.planning`'s private
    `_detect_cycle` (not exported) or `app.engine.workflow.graph`'s
    algorithm -- same documented precedent as `app.contracts.planning`
    itself: structurally similar by design, independently defined, since a
    manager-proposal validator must never import from the contracts layer's
    private internals.
    """
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


class ManagerResponse(BaseModel):
    """A `ManagerModel`'s full structured proposal for one `ManagerRequest`.

    Everything here is a *proposal*: nothing on this type can mutate
    workflow state, mark verification as passed, fabricate Agent Passport
    evidence, or select a tool for execution. `ManagerProposalValidator`
    (`validation.py`) must accept it, and even then `ManagerOrchestrator`
    (`orchestrator.py`) only ever folds the validated `preferred_agent_types`
    into a deterministic `RoutingConstraints` -- every other field is
    observability/evidence only.
    """

    model_config = ConfigDict(extra="forbid")

    request_id: str
    goal_interpretation: str | None = None
    task_proposals: list[ManagerTaskProposal] = Field(default_factory=list)
    requested_knowledge_queries: list[str] = Field(default_factory=list)
    recovery_recommendation: RecoveryAction | None = None
    clarification_required: bool = False
    clarification_question: str | None = None
    confidence: float | None = None
    evidence_summary: list[ManagerEvidenceRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    provider_identifier: str | None = None

    @field_validator("request_id")
    @classmethod
    def _request_id_valid(cls, value: str) -> str:
        _not_blank(value, "request_id")
        if len(value) > MAX_IDENTIFIER_LENGTH:
            raise ValueError(f"request_id must not exceed {MAX_IDENTIFIER_LENGTH} characters")
        return value

    @field_validator("goal_interpretation")
    @classmethod
    def _goal_interpretation_valid(cls, value: str | None) -> str | None:
        if value is None:
            return value
        _not_blank(value, "goal_interpretation")
        if len(value) > MAX_GOAL_INTERPRETATION_LENGTH:
            raise ValueError(
                f"goal_interpretation must not exceed {MAX_GOAL_INTERPRETATION_LENGTH} characters"
            )
        return value

    @field_validator("task_proposals")
    @classmethod
    def _task_proposals_bounded(cls, value: list[ManagerTaskProposal]) -> list[ManagerTaskProposal]:
        if len(value) > MAX_TASK_PROPOSALS:
            raise ValueError(
                f"task_proposals must not contain more than {MAX_TASK_PROPOSALS} entries"
            )
        return value

    @field_validator("requested_knowledge_queries")
    @classmethod
    def _requested_knowledge_queries_bounded(cls, value: list[str]) -> list[str]:
        return _bounded_unique_strings(
            value,
            "requested_knowledge_queries",
            max_items=MAX_KNOWLEDGE_NEEDS,
            max_length=MAX_KNOWLEDGE_QUERY_LENGTH,
        )

    @field_validator("clarification_question")
    @classmethod
    def _clarification_question_valid(cls, value: str | None) -> str | None:
        if value is None:
            return value
        _not_blank(value, "clarification_question")
        if len(value) > MAX_CLARIFICATION_QUESTION_LENGTH:
            raise ValueError(
                "clarification_question must not exceed "
                f"{MAX_CLARIFICATION_QUESTION_LENGTH} characters"
            )
        return value

    @field_validator("confidence")
    @classmethod
    def _confidence_bounded(cls, value: float | None) -> float | None:
        if value is not None and not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return value

    @field_validator("evidence_summary")
    @classmethod
    def _evidence_summary_bounded(cls, value: list[ManagerEvidenceRef]) -> list[ManagerEvidenceRef]:
        if len(value) > MAX_EVIDENCE_ITEMS:
            raise ValueError(
                f"evidence_summary must not contain more than {MAX_EVIDENCE_ITEMS} items"
            )
        return value

    @field_validator("warnings")
    @classmethod
    def _warnings_bounded(cls, value: list[str]) -> list[str]:
        if len(value) > MAX_WARNINGS:
            raise ValueError(f"warnings must not contain more than {MAX_WARNINGS} entries")
        for entry in value:
            if not entry.strip():
                raise ValueError("warnings entries must not be blank")
            if len(entry) > MAX_WARNING_LENGTH:
                raise ValueError(
                    f"warnings entries must not exceed {MAX_WARNING_LENGTH} characters"
                )
        return value

    @field_validator("provider_identifier")
    @classmethod
    def _provider_identifier_valid(cls, value: str | None) -> str | None:
        if value is None:
            return value
        _not_blank(value, "provider_identifier")
        if len(value) > MAX_PROVIDER_IDENTIFIER_LENGTH:
            raise ValueError(
                f"provider_identifier must not exceed {MAX_PROVIDER_IDENTIFIER_LENGTH} characters"
            )
        return value

    @model_validator(mode="after")
    def _clarification_consistency(self) -> "ManagerResponse":
        """Mirrors `AgentExecutionResult`'s never-silently-coerced pairing
        discipline: a clarification question with `clarification_required=False`,
        or a `True` flag with no question, is a contradiction, not a valid
        proposal."""
        if self.clarification_required and not (
            self.clarification_question and self.clarification_question.strip()
        ):
            raise ValueError(
                "clarification_question is required when clarification_required is True"
            )
        if not self.clarification_required and self.clarification_question is not None:
            raise ValueError(
                "clarification_question must be None when clarification_required is False"
            )
        return self

    @model_validator(mode="after")
    def _unique_keys_known_dependencies_no_cycles(self) -> "ManagerResponse":
        """Structurally mirrors `WorkflowPlan`'s own validator (`app.contracts.planning`):
        unique task keys, only known dependency references, no cycles.
        Unknown/malformed dependency shapes fail closed at construction --
        a `ManagerResponse` this invalid cannot exist, let alone reach
        `ManagerProposalValidator`."""
        keys = [task.key for task in self.task_proposals]
        if len(keys) != len(set(keys)):
            raise ValueError("task_proposals keys must be unique within a response")
        known = set(keys)
        for task in self.task_proposals:
            unknown = [dep for dep in task.depends_on if dep not in known]
            if unknown:
                raise ValueError(
                    f"task '{task.key}' depends on undeclared task(s): {', '.join(unknown)}"
                )

        cycle = _detect_cycle({task.key: task for task in self.task_proposals})
        if cycle is not None:
            raise ValueError(
                f"manager response task_proposals contain a cycle: {' -> '.join(cycle)}"
            )
        return self


__all__ = [
    "MAX_AVAILABLE_AGENT_TYPES",
    "MAX_AVAILABLE_CAPABILITIES",
    "MAX_CAPABILITIES_PER_TASK",
    "MAX_CLARIFICATION_QUESTION_LENGTH",
    "MAX_DEPENDENCIES_PER_TASK",
    "MAX_EVIDENCE_DESCRIPTION_LENGTH",
    "MAX_EVIDENCE_ITEMS",
    "MAX_EVIDENCE_KIND_LENGTH",
    "MAX_EVIDENCE_SOURCE_LENGTH",
    "MAX_EXCLUDED_AGENT_TYPES",
    "MAX_FAILURE_SUMMARY_LENGTH",
    "MAX_GOAL_INTERPRETATION_LENGTH",
    "MAX_GOAL_LENGTH",
    "MAX_IDENTIFIER_LENGTH",
    "MAX_KNOWLEDGE_CONTEXT_ITEMS",
    "MAX_KNOWLEDGE_NEEDS",
    "MAX_KNOWLEDGE_QUERY_LENGTH",
    "MAX_PREFERRED_AGENTS_PER_TASK",
    "MAX_PROVIDER_IDENTIFIER_LENGTH",
    "MAX_REPOSITORY_ID_LENGTH",
    "MAX_TASK_DESCRIPTION_LENGTH",
    "MAX_TASK_PROPOSALS",
    "MAX_TASK_TYPE_LENGTH",
    "MAX_WARNINGS",
    "MAX_WARNING_LENGTH",
    "ManagerEvidenceRef",
    "ManagerRecoveryContext",
    "ManagerRequest",
    "ManagerResponse",
    "ManagerTaskProposal",
]
