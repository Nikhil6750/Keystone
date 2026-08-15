"""Stage 9C Objective Skill Evidence & Empirical Metrics.

Keystone rule: ONLY objective execution outcomes can update reliability.
No model self-reports or "this worked" assertions are ever counted.
A run is successful IF AND ONLY IF `verification_status is VerificationStatus.PASSED`.

Neutral priors:
Uses Bayesian smoothed reliability:
    smoothed_reliability = (successes + prior_alpha) / (total + prior_alpha + prior_beta)
with default alpha=1.0, beta=1.0 yielding a neutral 0.5 prior when sample count is 0.
This ensures one success does not dominate and one failure does not permanently suppress.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from app.contracts.verification import VerificationStatus
from app.engine.skills.errors import SkillValidationError


@dataclass(frozen=True)
class SkillExecutionEvidence:
    """One objective, verified execution outcome attributed to a skill."""

    skill_id: str
    skill_version: str
    task_type: str
    agent_id: str
    execution_id: str
    task_id: str
    verification_status: VerificationStatus
    success: bool
    failure_category: str | None = None
    latency_ms: float = 0.0
    recovery_required: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.skill_id.strip():
            raise SkillValidationError("skill_id must not be blank in evidence")
        if not self.skill_version.strip():
            raise SkillValidationError("skill_version must not be blank in evidence")
        if not self.task_type.strip():
            raise SkillValidationError("task_type must not be blank in evidence")
        if not self.agent_id.strip():
            raise SkillValidationError("agent_id must not be blank in evidence")
        if not self.execution_id.strip():
            raise SkillValidationError("execution_id must not be blank in evidence")
        if not self.task_id.strip():
            raise SkillValidationError("task_id must not be blank in evidence")

        # Hard invariant: success is derived strictly from objective verification
        expected_success = self.verification_status is VerificationStatus.PASSED
        if self.success != expected_success:
            object.__setattr__(self, "success", expected_success)


@dataclass(frozen=True)
class SkillMetricsSummary:
    """Empirical reliability metrics computed over objective execution evidence."""

    skill_id: str
    skill_version: str | None = None  # None indicates aggregated over all versions
    total_samples: int = 0
    verified_successes: int = 0
    verified_failures: int = 0
    inconclusive_count: int = 0
    severe_failures: int = 0
    recovery_count: int = 0
    mean_latency_ms: float = 0.0

    @property
    def raw_success_rate(self) -> float | None:
        """True empirical success rate, or None if no conclusive samples exist."""
        conclusive = self.verified_successes + self.verified_failures
        if conclusive == 0:
            return None
        return self.verified_successes / conclusive

    def smoothed_reliability(self, prior_alpha: float = 1.0, prior_beta: float = 1.0) -> float:
        """Bayesian smoothed reliability with neutral prior (default 0.5 at 0 samples)."""
        conclusive = self.verified_successes + self.verified_failures
        return (self.verified_successes + prior_alpha) / (conclusive + prior_alpha + prior_beta)

    @property
    def recovery_rate(self) -> float:
        if self.total_samples == 0:
            return 0.0
        return self.recovery_count / self.total_samples


class SkillEvidenceRepository(Protocol):
    """Protocol for reading and recording skill execution evidence."""

    def record_evidence(self, evidence: SkillExecutionEvidence) -> None:
        """Record an objective execution evidence event."""
        ...

    def get_evidence_for_skill(
        self, skill_id: str, version: str | None = None
    ) -> list[SkillExecutionEvidence]:
        """Get all evidence records for a given skill (and optional version)."""
        ...

    def get_metrics_for_skill(
        self, skill_id: str, version: str | None = None
    ) -> SkillMetricsSummary:
        """Compute aggregated metrics for a given skill."""
        ...

    def get_all_evidence(self) -> list[SkillExecutionEvidence]:
        """Return all stored evidence in deterministic order."""
        ...


class InMemorySkillEvidenceRepository:
    """In-memory implementation of SkillEvidenceRepository."""

    def __init__(self, initial_records: Iterable[SkillExecutionEvidence] = ()) -> None:
        self._records: list[SkillExecutionEvidence] = []
        for r in initial_records:
            self.record_evidence(r)

    def record_evidence(self, evidence: SkillExecutionEvidence) -> None:
        self._records.append(evidence)

    def get_evidence_for_skill(
        self, skill_id: str, version: str | None = None
    ) -> list[SkillExecutionEvidence]:
        return [
            r
            for r in self._records
            if r.skill_id == skill_id and (version is None or r.skill_version == version)
        ]

    def get_metrics_for_skill(
        self, skill_id: str, version: str | None = None
    ) -> SkillMetricsSummary:
        records = self.get_evidence_for_skill(skill_id, version)
        if not records:
            return SkillMetricsSummary(skill_id=skill_id, skill_version=version)

        total = len(records)
        successes = sum(1 for r in records if r.verification_status is VerificationStatus.PASSED)
        failures = sum(1 for r in records if r.verification_status is VerificationStatus.FAILED)
        inconclusives = total - successes - failures
        severe = sum(
            1
            for r in records
            if r.failure_category
            in ("FATAL_SYSTEM_ERROR", "CORRUPT_STATE", "SECURITY_VIOLATION", "SEVERE")
        )
        recoveries = sum(1 for r in records if r.recovery_required)
        mean_lat = sum(r.latency_ms for r in records) / total if total > 0 else 0.0

        return SkillMetricsSummary(
            skill_id=skill_id,
            skill_version=version,
            total_samples=total,
            verified_successes=successes,
            verified_failures=failures,
            inconclusive_count=inconclusives,
            severe_failures=severe,
            recovery_count=recoveries,
            mean_latency_ms=mean_lat,
        )

    def get_all_evidence(self) -> list[SkillExecutionEvidence]:
        return list(self._records)


__all__ = [
    "InMemorySkillEvidenceRepository",
    "SkillEvidenceRepository",
    "SkillExecutionEvidence",
    "SkillMetricsSummary",
]
