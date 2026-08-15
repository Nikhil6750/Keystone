"""Stage 9D Domain Contracts: Software Quality Factory.

Preserves the core Keystone conceptual separation:
    Task = WHAT
    Skill = HOW
    Agent = WHO
    Quality Contract = WHAT MUST BE TRUE BEFORE THE SOFTWARE IS ACCEPTED

Defines provider-neutral data models for Quality Profiles, Quality Gate Specs,
Quality Evidence, Quality Gate Results, Quality Verdicts, and Quality Runs.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.contracts.evidence_safety import reject_reasoning_shaped_keys


class QualityGateStatus(StrEnum):
    """Execution status for a single quality gate."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


class QualityVerdictStatus(StrEnum):
    """Aggregate quality verdict for a software quality run."""

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    REPAIR_REQUIRED = "REPAIR_REQUIRED"
    ERROR = "ERROR"


class QualityGateType(StrEnum):
    """Standardized quality gate categories."""

    TEST = "test"
    LINT = "lint"
    TYPE_CHECK = "type_check"
    BUILD = "build"
    CUSTOM = "custom"


class QualityContractValidationError(ValueError):
    """Raised when a quality contract violates validation invariants."""


# Regex to detect dangerous shell injection characters in identifiers or arguments
_SHELL_INJECTION_PATTERN = re.compile(r"[;&|`$><\n\r]")


@dataclass(frozen=True)
class QualityGateSpec:
    """Specification of one software verification requirement."""

    gate_id: str
    gate_type: QualityGateType | str
    name: str
    required: bool = True
    timeout_seconds: float = 30.0
    applicable_scope: str = "workspace"
    configuration: dict[str, Any] = field(default_factory=dict)
    order: int = 0

    def __post_init__(self) -> None:
        if not self.gate_id or not self.gate_id.strip():
            raise QualityContractValidationError("gate_id must not be blank")
        if _SHELL_INJECTION_PATTERN.search(self.gate_id):
            raise QualityContractValidationError(
                f"gate_id contains disallowed shell characters: {self.gate_id!r}"
            )
        if not self.name or not self.name.strip():
            raise QualityContractValidationError("name must not be blank")
        if self.timeout_seconds <= 0.0 or self.timeout_seconds > 600.0:
            raise QualityContractValidationError(
                f"timeout_seconds must be between 0 and 600, got {self.timeout_seconds}"
            )
        if isinstance(self.gate_type, str):
            try:
                g_enum = QualityGateType(self.gate_type.lower())
                object.__setattr__(self, "gate_type", g_enum)
            except ValueError as exc:
                # Custom gate type allowed if non-blank and safe
                if not self.gate_type.strip():
                    raise QualityContractValidationError("gate_type must not be blank") from exc
                if _SHELL_INJECTION_PATTERN.search(self.gate_type):
                    raise QualityContractValidationError(
                        f"gate_type contains disallowed shell characters: {self.gate_type!r}"
                    ) from exc


@dataclass(frozen=True)
class QualityProfile:
    """Reusable quality expectations for a repository, workflow, or task."""

    profile_id: str
    name: str
    description: str = ""
    target_languages: tuple[str, ...] = field(default_factory=tuple)
    target_frameworks: tuple[str, ...] = field(default_factory=tuple)
    gates: tuple[QualityGateSpec, ...] = field(default_factory=tuple)
    is_default: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.profile_id or not self.profile_id.strip():
            raise QualityContractValidationError("profile_id must not be blank")
        if not self.name or not self.name.strip():
            raise QualityContractValidationError("name must not be blank")

        # Validate unique gate_ids in profile
        gate_ids = [g.gate_id for g in self.gates]
        if len(gate_ids) != len(set(gate_ids)):
            raise QualityContractValidationError(
                f"Duplicate gate_ids detected in profile '{self.profile_id}'"
            )


@dataclass(frozen=True)
class QualityEvidence:
    """Bounded, observable evidence captured during quality gate execution."""

    summary: str
    exit_code: int | None = None
    diagnostics: tuple[str, ...] = field(default_factory=tuple)
    artifact_references: tuple[str, ...] = field(default_factory=tuple)
    stdout: str = ""
    stderr: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Enforce evidence safety: no reasoning traces or unrestricted dicts
        try:
            reject_reasoning_shaped_keys(self.metrics)
        except ValueError as exc:
            raise QualityContractValidationError(f"Unsafe evidence metrics: {exc}") from exc


@dataclass(frozen=True)
class QualityGateResult:
    """Normalized result of executing one QualityGateSpec."""

    gate_id: str
    gate_type: QualityGateType | str
    name: str
    status: QualityGateStatus
    required: bool
    evidence: QualityEvidence
    execution_time_ms: float = 0.0
    failure_reason: str | None = None
    skip_reason: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.gate_id or not self.gate_id.strip():
            raise QualityContractValidationError("gate_id must not be blank")
        if self.status is QualityGateStatus.FAILED and not (
            self.failure_reason and self.failure_reason.strip()
        ):
            # Provide default failure reason from evidence if not explicitly passed
            if self.evidence and self.evidence.summary:
                object.__setattr__(self, "failure_reason", self.evidence.summary)
            else:
                raise QualityContractValidationError(
                    "failure_reason is required when gate status is FAILED"
                )
        if self.status is QualityGateStatus.PASSED and self.failure_reason is not None:
            raise QualityContractValidationError(
                "failure_reason must be None when gate status is PASSED"
            )


@dataclass(frozen=True)
class QualityVerdict:
    """Deterministic aggregate quality verdict across all executed quality gates."""

    verdict_id: str
    status: QualityVerdictStatus
    passed: bool
    blocking_failures: tuple[QualityGateResult, ...]
    advisory_failures: tuple[QualityGateResult, ...]
    total_gates: int
    passed_gates: int
    failed_gates: int
    skipped_gates: int
    error_gates: int
    summary_explanation: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def compute(
        cls,
        gate_results: list[QualityGateResult] | tuple[QualityGateResult, ...],
        verdict_id: str | None = None,
    ) -> QualityVerdict:
        """Deterministically compute an aggregate verdict from concrete gate results."""
        v_id = verdict_id or str(uuid.uuid4())
        results = tuple(gate_results)

        passed_count = sum(1 for r in results if r.status is QualityGateStatus.PASSED)
        failed_count = sum(1 for r in results if r.status is QualityGateStatus.FAILED)
        error_count = sum(1 for r in results if r.status is QualityGateStatus.ERROR)
        skipped_count = sum(1 for r in results if r.status is QualityGateStatus.SKIPPED)

        blocking = tuple(
            r
            for r in results
            if r.required and r.status in (QualityGateStatus.FAILED, QualityGateStatus.ERROR)
        )
        advisory = tuple(
            r
            for r in results
            if not r.required and r.status in (QualityGateStatus.FAILED, QualityGateStatus.ERROR)
        )

        if not results:
            # Zero gates executed -> Neutral Acceptance
            return cls(
                verdict_id=v_id,
                status=QualityVerdictStatus.ACCEPTED,
                passed=True,
                blocking_failures=(),
                advisory_failures=(),
                total_gates=0,
                passed_gates=0,
                failed_gates=0,
                skipped_gates=0,
                error_gates=0,
                summary_explanation="No quality gates were configured or executed.",
            )

        if blocking:
            # Required gate failure or error blocks acceptance
            has_error = any(r.status is QualityGateStatus.ERROR for r in blocking)
            status = QualityVerdictStatus.ERROR if has_error else QualityVerdictStatus.REJECTED
            failed_names = ", ".join(f"'{r.name}' ({r.gate_id})" for r in blocking)
            explanation = (
                f"Quality verification failed: {len(blocking)} required gate(s) failed: "
                f"{failed_names}."
            )
            return cls(
                verdict_id=v_id,
                status=status,
                passed=False,
                blocking_failures=blocking,
                advisory_failures=advisory,
                total_gates=len(results),
                passed_gates=passed_count,
                failed_gates=failed_count,
                skipped_gates=skipped_count,
                error_gates=error_count,
                summary_explanation=explanation,
            )

        # All required gates passed (or skipped with justification)
        status = QualityVerdictStatus.ACCEPTED
        explanation = (
            f"Quality verification passed: {passed_count}/{len(results)} gates passed successfully."
        )
        if advisory:
            explanation += f" ({len(advisory)} advisory check(s) reported warnings)."

        return cls(
            verdict_id=v_id,
            status=status,
            passed=True,
            blocking_failures=(),
            advisory_failures=advisory,
            total_gates=len(results),
            passed_gates=passed_count,
            failed_gates=failed_count,
            skipped_gates=skipped_count,
            error_gates=error_count,
            summary_explanation=explanation,
        )


@dataclass(frozen=True)
class QualityRun:
    """Represents one execution of a quality plan against a software outcome."""

    run_id: str
    execution_id: str
    workflow_id: str | None = None
    task_id: str | None = None
    attempt_number: int = 1
    agent_id: str | None = None
    skill_id: str | None = None
    skill_version: str | None = None
    profile_id: str | None = None
    gate_results: tuple[QualityGateResult, ...] = field(default_factory=tuple)
    verdict: QualityVerdict | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.run_id or not self.run_id.strip():
            raise QualityContractValidationError("run_id must not be blank")
        if not self.execution_id or not self.execution_id.strip():
            raise QualityContractValidationError("execution_id must not be blank")


@dataclass(frozen=True)
class QualityRepairPacket:
    """Structured failure context sent to existing orchestration recovery loops."""

    run_id: str
    task_id: str
    execution_id: str
    attempt_number: int
    max_repair_attempts: int
    blocking_gate_ids: tuple[str, ...]
    failure_summaries: tuple[str, ...]
    diagnostics: tuple[str, ...]
    affected_artifacts: tuple[str, ...]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def has_repairs_remaining(self) -> bool:
        return self.attempt_number < self.max_repair_attempts


@dataclass(frozen=True)
class QualityExecutionContext:
    """Runtime context provided to quality gate executors."""

    workspace_root: str
    repository_id: str | None = None
    languages: tuple[str, ...] = field(default_factory=tuple)
    frameworks: tuple[str, ...] = field(default_factory=tuple)
    task_type: str = ""
    task_id: str = ""
    execution_id: str = ""
    agent_id: str | None = None
    skill_id: str | None = None
    skill_version: str | None = None
    environment_overrides: dict[str, str] = field(default_factory=dict)


__all__ = [
    "QualityContractValidationError",
    "QualityEvidence",
    "QualityExecutionContext",
    "QualityGateResult",
    "QualityGateSpec",
    "QualityGateStatus",
    "QualityGateType",
    "QualityProfile",
    "QualityRepairPacket",
    "QualityRun",
    "QualityVerdict",
    "QualityVerdictStatus",
]
