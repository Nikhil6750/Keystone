"""Stage 9C Domain Contracts: Provider-Neutral Typed Skill Models, Lifecycle, and Assignments.

Keystone differentiator: VERIFIED OUTCOME INTELLIGENCE.
Task = WHAT
Skill = HOW
Agent = WHO

Skills define reusable procedures, preconditions, and verification contracts.
Agent performance belongs in evidence, NOT in the base skill definition.
Provider-specific fields (preferred_codex, preferred_claude, preferred_antigravity, etc.)
are strictly forbidden in the skill definition.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.contracts.enums import AgentCapability
from app.contracts.verification import VerificationStatus


class SkillStatus(StrEnum):
    """Lifecycle states for skills in Keystone."""

    DRAFT = "DRAFT"  # Human-created or machine-created but untested
    CANDIDATE = "CANDIDATE"  # Has enough structural validity/evidence to evaluate
    VERIFIED = "VERIFIED"  # Passed objective verification in real executions
    TRUSTED = "TRUSTED"  # Sufficient sample size + reliability threshold
    DEPRECATED = "DEPRECATED"  # Superseded or performance degraded


class SkillCategory(StrEnum):
    """Broad domain categories for organizing skills in the vault."""

    BACKEND = "Backend"
    FRONTEND = "Frontend"
    TESTING = "Testing"
    DATA_ENGINEERING = "DataEngineering"
    DEVOPS = "DevOps"
    DEBUGGING = "Debugging"
    GENERAL = "General"


_FORBIDDEN_PROVIDER_FIELD_PREFIXES = (
    "preferred_codex",
    "preferred_claude",
    "preferred_antigravity",
    "preferred_agent",
    "codex_",
    "claude_",
    "antigravity_",
)


class SkillContractValidationError(ValueError):
    """Raised when a skill definition violates typing or neutral contract invariants."""


@dataclass(frozen=True)
class SkillContract:
    """Provider-neutral typed Skill model.

    Defines HOW to perform a task. Must not contain provider-specific routing preferences.
    """

    skill_id: str
    version: str
    name: str
    description: str
    category: SkillCategory | str
    task_types: tuple[str, ...] = field(default_factory=tuple)
    capabilities: tuple[AgentCapability, ...] = field(default_factory=tuple)
    languages: tuple[str, ...] = field(default_factory=tuple)
    frameworks: tuple[str, ...] = field(default_factory=tuple)
    preconditions: tuple[str, ...] = field(default_factory=tuple)
    contraindications: tuple[str, ...] = field(default_factory=tuple)
    procedure: str = ""
    verification_contract: dict[str, Any] = field(default_factory=dict)
    source: str = "obsidian_vault"
    provenance: dict[str, Any] = field(default_factory=dict)
    status: SkillStatus = SkillStatus.DRAFT
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.skill_id or not self.skill_id.strip():
            raise SkillContractValidationError("skill_id must not be blank")
        if not self.version or not self.version.strip():
            raise SkillContractValidationError("version must not be blank")
        if not self.name or not self.name.strip():
            raise SkillContractValidationError("name must not be blank")

        # Check for forbidden provider-specific fields in provenance or custom keys
        for key in self.provenance:
            for forbidden in _FORBIDDEN_PROVIDER_FIELD_PREFIXES:
                if key.lower().startswith(forbidden):
                    raise SkillContractValidationError(
                        f"Provider-specific field '{key}' is forbidden in SkillContract. "
                        "Agent performance belongs in SkillEvidence, not SkillContract."
                    )

        # Normalize category
        if isinstance(self.category, str):
            try:
                cat_enum = SkillCategory(self.category)
                object.__setattr__(self, "category", cat_enum)
            except ValueError as err:
                # Allow custom or fallback to string if valid non-empty
                if not self.category.strip():
                    raise SkillContractValidationError("category must not be blank") from err

        # Normalize status
        if isinstance(self.status, str):
            try:
                st_enum = SkillStatus(self.status)
                object.__setattr__(self, "status", st_enum)
            except ValueError as err:
                raise SkillContractValidationError(
                    f"Invalid skill status: {self.status}"
                ) from err

    def is_eligible_for_retrieval(self) -> bool:
        """Deprecated skills are not eligible for active retrieval."""
        return self.status != SkillStatus.DEPRECATED


@dataclass(frozen=True)
class SkillAssignment:
    """Record of a skill attached to a TaskGraph node."""

    task_id: str
    skill_id: str
    skill_version: str
    skill_name: str
    category: str
    match_score: float
    rationale: str
    assigned_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class SkillExecutionTrace:
    """Provenance tracking skill attachment through execution and verification."""

    execution_id: str
    task_id: str
    skill_id: str
    skill_version: str
    agent_id: str
    task_type: str
    verification_status: VerificationStatus
    success: bool
    latency_ms: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


__all__ = [
    "SkillAssignment",
    "SkillCategory",
    "SkillContract",
    "SkillContractValidationError",
    "SkillExecutionTrace",
    "SkillStatus",
]
