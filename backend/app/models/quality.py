"""SQLAlchemy ORM models for Stage 9D Software Quality Factory persistence."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.contracts.quality import (
    QualityEvidence,
    QualityGateResult,
    QualityGateSpec,
    QualityGateStatus,
    QualityGateType,
    QualityProfile,
    QualityRun,
    QualityVerdict,
    QualityVerdictStatus,
)
from app.database.base import Base


class QualityProfileRecord(Base):
    """Persisted quality profile definition containing reusable quality expectations."""

    __tablename__ = "quality_profiles"
    __table_args__ = (
        UniqueConstraint("profile_id", name="uq_quality_profile_id"),
        CheckConstraint("length(trim(profile_id)) > 0", name="ck_quality_profile_id_not_blank"),
        CheckConstraint("length(trim(name)) > 0", name="ck_quality_profile_name_not_blank"),
    )

    profile_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    target_languages: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    target_frameworks: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    gates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    def to_contract(self) -> QualityProfile:
        gate_specs: list[QualityGateSpec] = []
        for g in self.gates:
            gate_specs.append(
                QualityGateSpec(
                    gate_id=g.get("gate_id", ""),
                    gate_type=g.get("gate_type", "custom"),
                    name=g.get("name", ""),
                    required=g.get("required", True),
                    timeout_seconds=float(g.get("timeout_seconds", 30.0)),
                    applicable_scope=g.get("applicable_scope", "workspace"),
                    configuration=dict(g.get("configuration", {})),
                    order=int(g.get("order", 0)),
                )
            )

        return QualityProfile(
            profile_id=self.profile_id,
            name=self.name,
            description=self.description,
            target_languages=tuple(self.target_languages),
            target_frameworks=tuple(self.target_frameworks),
            gates=tuple(gate_specs),
            is_default=self.is_default,
            metadata=dict(self.metadata_json),
        )

    @classmethod
    def from_contract(cls, p: QualityProfile) -> QualityProfileRecord:
        serialized_gates = [
            {
                "gate_id": g.gate_id,
                "gate_type": g.gate_type.value
                if isinstance(g.gate_type, QualityGateType)
                else str(g.gate_type),
                "name": g.name,
                "required": g.required,
                "timeout_seconds": g.timeout_seconds,
                "applicable_scope": g.applicable_scope,
                "configuration": g.configuration,
                "order": g.order,
            }
            for g in p.gates
        ]
        return cls(
            profile_id=p.profile_id,
            name=p.name,
            description=p.description,
            target_languages=list(p.target_languages),
            target_frameworks=list(p.target_frameworks),
            gates=serialized_gates,
            is_default=p.is_default,
            metadata_json=dict(p.metadata),
        )


class QualityRunRecord(Base):
    """Persisted record of one quality verification execution."""

    __tablename__ = "quality_runs"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_quality_run_id"),
        UniqueConstraint(
            "execution_id", "task_id", "attempt_number", name="uq_quality_run_attempt"
        ),
    )

    run_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    execution_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    workflow_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    task_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    agent_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    skill_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    skill_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    profile_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="REJECTED")
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    total_gates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed_gates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_gates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_gates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_gates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary_explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def to_verdict(
        self, gate_results: list[QualityGateResult] | tuple[QualityGateResult, ...] = ()
    ) -> QualityVerdict:
        v_status = (
            QualityVerdictStatus(self.status)
            if self.status in QualityVerdictStatus._value2member_map_
            else QualityVerdictStatus.REJECTED
        )
        blocking = tuple(
            r
            for r in gate_results
            if r.required and r.status is not QualityGateStatus.PASSED
        )
        advisory = tuple(
            r
            for r in gate_results
            if not r.required and r.status is not QualityGateStatus.PASSED
        )
        return QualityVerdict(
            verdict_id=f"verdict-{self.run_id}",
            status=v_status,
            passed=self.passed,
            blocking_failures=blocking,
            advisory_failures=advisory,
            total_gates=self.total_gates,
            passed_gates=self.passed_gates,
            failed_gates=self.failed_gates,
            skipped_gates=self.skipped_gates,
            error_gates=self.error_gates,
            summary_explanation=self.summary_explanation,
            created_at=self.completed_at or self.created_at,
        )

    def to_contract(
        self, gate_results: list[QualityGateResult] | tuple[QualityGateResult, ...] = ()
    ) -> QualityRun:
        verdict = self.to_verdict(gate_results)
        return QualityRun(
            run_id=self.run_id,
            execution_id=self.execution_id,
            workflow_id=self.workflow_id,
            task_id=self.task_id,
            attempt_number=self.attempt_number,
            agent_id=self.agent_id,
            skill_id=self.skill_id,
            skill_version=self.skill_version,
            profile_id=self.profile_id,
            gate_results=tuple(gate_results),
            verdict=verdict,
            created_at=self.created_at,
            completed_at=self.completed_at,
        )

    @classmethod
    def from_contract(cls, run: QualityRun) -> QualityRunRecord:
        verdict = run.verdict
        status_val = verdict.status.value if verdict else QualityVerdictStatus.REJECTED.value
        passed_val = verdict.passed if verdict else False
        tot = verdict.total_gates if verdict else len(run.gate_results)
        pass_cnt = verdict.passed_gates if verdict else 0
        fail_cnt = verdict.failed_gates if verdict else 0
        skip_cnt = verdict.skipped_gates if verdict else 0
        err_cnt = verdict.error_gates if verdict else 0
        expl = verdict.summary_explanation if verdict else ""

        return cls(
            run_id=run.run_id,
            execution_id=run.execution_id,
            workflow_id=run.workflow_id,
            task_id=run.task_id,
            attempt_number=run.attempt_number,
            agent_id=run.agent_id,
            skill_id=run.skill_id,
            skill_version=run.skill_version,
            profile_id=run.profile_id,
            status=status_val,
            passed=passed_val,
            total_gates=tot,
            passed_gates=pass_cnt,
            failed_gates=fail_cnt,
            skipped_gates=skip_cnt,
            error_gates=err_cnt,
            summary_explanation=expl,
            created_at=run.created_at,
            completed_at=run.completed_at,
        )


class QualityGateResultRecord(Base):
    """Persisted outcome and evidence for one executed quality gate."""

    __tablename__ = "quality_gate_results"
    __table_args__ = (
        UniqueConstraint("run_id", "gate_id", name="uq_quality_gate_result_run_gate"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    run_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    execution_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    task_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    gate_id: Mapped[str] = mapped_column(String(100), nullable=False)
    gate_type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    diagnostics: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    artifact_references: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    stdout: Mapped[str] = mapped_column(Text, nullable=False, default="")
    stderr: Mapped[str] = mapped_column(Text, nullable=False, default="")

    execution_time_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    skip_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    def to_contract(self) -> QualityGateResult:
        g_status = (
            QualityGateStatus(self.status)
            if self.status in QualityGateStatus._value2member_map_
            else QualityGateStatus.FAILED
        )
        g_type = (
            QualityGateType(self.gate_type)
            if self.gate_type in QualityGateType._value2member_map_
            else self.gate_type
        )
        evidence = QualityEvidence(
            summary=self.summary
            or self.failure_reason
            or f"Gate '{self.name}' status: {self.status}",
            exit_code=self.exit_code,
            diagnostics=tuple(self.diagnostics),
            artifact_references=tuple(self.artifact_references),
            stdout=self.stdout,
            stderr=self.stderr,
            metrics=dict(self.metrics),
        )
        return QualityGateResult(
            gate_id=self.gate_id,
            gate_type=g_type,
            name=self.name,
            status=g_status,
            required=self.required,
            evidence=evidence,
            execution_time_ms=self.execution_time_ms,
            failure_reason=self.failure_reason,
            skip_reason=self.skip_reason,
            timestamp=self.timestamp,
        )

    @classmethod
    def from_contract(
        cls,
        r: QualityGateResult,
        run_id: str,
        execution_id: str,
        task_id: str | None = None,
        attempt_number: int = 1,
    ) -> QualityGateResultRecord:
        status_str = r.status.value if isinstance(r.status, QualityGateStatus) else str(r.status)
        type_str = (
            r.gate_type.value if isinstance(r.gate_type, QualityGateType) else str(r.gate_type)
        )

        return cls(
            id=str(uuid.uuid4()),
            run_id=run_id,
            execution_id=execution_id,
            task_id=task_id,
            attempt_number=attempt_number,
            gate_id=r.gate_id,
            gate_type=type_str,
            name=r.name,
            status=status_str,
            required=r.required,
            exit_code=r.evidence.exit_code if r.evidence else None,
            summary=r.evidence.summary if r.evidence else "",
            diagnostics=list(r.evidence.diagnostics) if r.evidence else [],
            artifact_references=list(r.evidence.artifact_references) if r.evidence else [],
            metrics=dict(r.evidence.metrics) if r.evidence else {},
            stdout=r.evidence.stdout if r.evidence else "",
            stderr=r.evidence.stderr if r.evidence else "",
            execution_time_ms=r.execution_time_ms,
            failure_reason=r.failure_reason,
            skip_reason=r.skip_reason,
            timestamp=r.timestamp,
        )


__all__ = [
    "QualityGateResultRecord",
    "QualityProfileRecord",
    "QualityRunRecord",
]
