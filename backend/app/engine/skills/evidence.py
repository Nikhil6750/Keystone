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
from typing import Any, Protocol

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
    """In-memory implementation of SkillEvidenceRepository with idempotency guarantees."""

    def __init__(self, initial_records: Iterable[SkillExecutionEvidence] = ()) -> None:
        self._records_by_key: dict[tuple[str, str, str, str], SkillExecutionEvidence] = {}
        for r in initial_records:
            self.record_evidence(r)

    def record_evidence(self, evidence: SkillExecutionEvidence) -> None:
        key = (
            evidence.execution_id,
            evidence.task_id,
            evidence.skill_id,
            evidence.skill_version,
        )
        self._records_by_key[key] = evidence

    def get_evidence_for_skill(
        self, skill_id: str, version: str | None = None
    ) -> list[SkillExecutionEvidence]:
        return [
            r
            for r in self._records_by_key.values()
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
        return list(self._records_by_key.values())


class SqlAlchemySkillEvidenceRepository:
    """Database-backed persistent implementation of SkillEvidenceRepository."""

    def __init__(self, session_factory: Any = None) -> None:
        if session_factory is None:
            from app.database.session import SessionLocal
            self._session_factory = SessionLocal
        else:
            self._session_factory = session_factory

    def _get_session(self) -> Any:
        if callable(self._session_factory):
            return self._session_factory()
        return self._session_factory

    def record_evidence(self, evidence: SkillExecutionEvidence) -> None:
        """Persist evidence record to database idempotently."""
        from app.models.skills import SkillEvidenceRecord

        session = self._get_session()
        try:
            existing = (
                session.query(SkillEvidenceRecord)
                .filter_by(
                    execution_id=evidence.execution_id,
                    task_id=evidence.task_id,
                    skill_id=evidence.skill_id,
                    skill_version=evidence.skill_version,
                )
                .first()
            )
            if existing is not None:
                # Update existing record idempotently
                existing.verification_status = (
                    evidence.verification_status.value
                    if isinstance(evidence.verification_status, VerificationStatus)
                    else str(evidence.verification_status)
                )
                existing.success = evidence.success
                existing.failure_category = evidence.failure_category
                existing.latency_ms = evidence.latency_ms
                existing.recovery_required = evidence.recovery_required
                existing.timestamp = evidence.timestamp
            else:
                record = SkillEvidenceRecord.from_evidence(evidence)
                session.add(record)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            if callable(self._session_factory):
                session.close()

    def get_evidence_for_skill(
        self, skill_id: str, version: str | None = None
    ) -> list[SkillExecutionEvidence]:
        from app.models.skills import SkillEvidenceRecord

        session = self._get_session()
        try:
            query = session.query(SkillEvidenceRecord).filter_by(skill_id=skill_id)
            if version is not None:
                query = query.filter_by(skill_version=version)
            query = query.order_by(SkillEvidenceRecord.timestamp.asc())
            rows = query.all()

            results = []
            for row in rows:
                v_status = (
                    VerificationStatus(row.verification_status)
                    if row.verification_status in VerificationStatus._value2member_map_
                    else VerificationStatus.INCONCLUSIVE
                )
                results.append(
                    SkillExecutionEvidence(
                        skill_id=row.skill_id,
                        skill_version=row.skill_version,
                        task_type=row.task_type,
                        agent_id=row.agent_id,
                        execution_id=row.execution_id,
                        task_id=row.task_id,
                        verification_status=v_status,
                        success=row.success,
                        failure_category=row.failure_category,
                        latency_ms=row.latency_ms,
                        recovery_required=row.recovery_required,
                        timestamp=row.timestamp,
                    )
                )
            return results
        finally:
            if callable(self._session_factory):
                session.close()

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
        from app.models.skills import SkillEvidenceRecord

        session = self._get_session()
        try:
            rows = (
                session.query(SkillEvidenceRecord)
                .order_by(SkillEvidenceRecord.timestamp.asc())
                .all()
            )
            results = []
            for row in rows:
                v_status = (
                    VerificationStatus(row.verification_status)
                    if row.verification_status in VerificationStatus._value2member_map_
                    else VerificationStatus.INCONCLUSIVE
                )
                results.append(
                    SkillExecutionEvidence(
                        skill_id=row.skill_id,
                        skill_version=row.skill_version,
                        task_type=row.task_type,
                        agent_id=row.agent_id,
                        execution_id=row.execution_id,
                        task_id=row.task_id,
                        verification_status=v_status,
                        success=row.success,
                        failure_category=row.failure_category,
                        latency_ms=row.latency_ms,
                        recovery_required=row.recovery_required,
                        timestamp=row.timestamp,
                    )
                )
            return results
        finally:
            if callable(self._session_factory):
                session.close()


__all__ = [
    "InMemorySkillEvidenceRepository",
    "SkillEvidenceRepository",
    "SkillExecutionEvidence",
    "SkillMetricsSummary",
    "SqlAlchemySkillEvidenceRepository",
]
