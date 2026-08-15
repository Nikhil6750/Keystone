"""SQLAlchemy ORM models for Skill Foundry persistence & evidence tracking."""

import contextlib
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.contracts.enums import AgentCapability
from app.contracts.skills import SkillCategory, SkillContract, SkillStatus
from app.contracts.verification import VerificationStatus
from app.database.base import Base


class SkillRecord(Base):
    """Persisted skill contract and version history in Keystone's database."""

    __tablename__ = "skills"
    __table_args__ = (
        UniqueConstraint("skill_id", "version", name="uq_skills_id_version"),
        CheckConstraint("length(trim(skill_id)) > 0", name="ck_skill_id_not_blank"),
        CheckConstraint("length(trim(version)) > 0", name="ck_skill_version_not_blank"),
        CheckConstraint("length(trim(name)) > 0", name="ck_skill_name_not_blank"),
    )

    skill_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    version: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="general")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="DRAFT")

    task_types: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    capabilities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    languages: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    frameworks: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    preconditions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    contraindications: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    procedure: Mapped[str] = mapped_column(Text, nullable=False, default="")
    verification_contract: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )

    source: Mapped[str] = mapped_column(String(100), nullable=False, default="manual")
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    def to_contract(self) -> SkillContract:
        """Convert ORM record to immutable SkillContract."""
        caps: list[AgentCapability] = []
        for c in self.capabilities:
            with contextlib.suppress(ValueError):
                caps.append(AgentCapability(c))

        cat = (
            SkillCategory(self.category)
            if self.category in SkillCategory._value2member_map_
            else self.category
        )
        st = (
            SkillStatus(self.status)
            if self.status in SkillStatus._value2member_map_
            else SkillStatus.DRAFT
        )

        return SkillContract(
            skill_id=self.skill_id,
            version=self.version,
            name=self.name,
            description=self.description,
            category=cat,
            task_types=tuple(self.task_types),
            capabilities=tuple(caps),
            languages=tuple(self.languages),
            frameworks=tuple(self.frameworks),
            preconditions=tuple(self.preconditions),
            contraindications=tuple(self.contraindications),
            procedure=self.procedure,
            verification_contract=dict(self.verification_contract),
            source=self.source,
            provenance=dict(self.provenance),
            status=st,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    @classmethod
    def from_contract(cls, s: SkillContract) -> "SkillRecord":
        """Create ORM record from SkillContract."""
        cat_str = s.category.value if isinstance(s.category, SkillCategory) else str(s.category)
        return cls(
            skill_id=s.skill_id,
            version=s.version,
            name=s.name,
            description=s.description,
            category=cat_str,
            status=s.status.value,
            task_types=list(s.task_types),
            capabilities=[c.value for c in s.capabilities],
            languages=list(s.languages),
            frameworks=list(s.frameworks),
            preconditions=list(s.preconditions),
            contraindications=list(s.contraindications),
            procedure=s.procedure,
            verification_contract=dict(s.verification_contract),
            source=s.source,
            provenance=dict(s.provenance),
            created_at=s.created_at,
            updated_at=s.updated_at,
        )


class SkillEvidenceRecord(Base):
    """Persisted objective verification evidence record for skill executions."""

    __tablename__ = "skill_evidence"
    __table_args__ = (
        UniqueConstraint(
            "execution_id", "task_id", "skill_id", "skill_version",
            name="uq_skill_evidence_idempotency"
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    execution_id: Mapped[str] = mapped_column(String(100), nullable=False)
    task_id: Mapped[str] = mapped_column(String(100), nullable=False)
    skill_id: Mapped[str] = mapped_column(String(100), nullable=False)
    skill_version: Mapped[str] = mapped_column(String(50), nullable=False)
    task_type: Mapped[str] = mapped_column(String(100), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(100), nullable=False)

    verification_status: Mapped[str] = mapped_column(String(50), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failure_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    recovery_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    @classmethod
    def from_evidence(cls, e: Any) -> "SkillEvidenceRecord":
        status_val = (
            e.verification_status.value
            if isinstance(e.verification_status, VerificationStatus)
            else str(e.verification_status)
        )
        return cls(
            id=str(uuid.uuid4()),
            execution_id=e.execution_id,
            task_id=e.task_id,
            skill_id=e.skill_id,
            skill_version=e.skill_version,
            task_type=e.task_type,
            agent_id=e.agent_id,
            verification_status=status_val,
            success=e.success,
            failure_category=e.failure_category,
            latency_ms=e.latency_ms,
            recovery_required=e.recovery_required,
            timestamp=e.timestamp,
        )


__all__ = ["SkillEvidenceRecord", "SkillRecord"]
