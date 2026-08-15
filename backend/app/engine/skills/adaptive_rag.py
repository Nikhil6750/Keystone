"""Stage 9C Outcome-Grounded Adaptive RAG for Skills.

Integrates skill retrieval decisions with objective execution outcomes.

Mechanism:
1. Records `SkillRetrievalObservation`: task fingerprint, retrieved skill candidates,
   selected skill ID, agent, and execution ID.
2. Upon objective verification (`VerificationStatus.PASSED` / `FAILED`), records
   `SkillRetrievalFeedback`.
3. Updates skill retrieval utility with bounded learning rates:
   - Positive outcome increases skill utility for that task type / query pattern.
   - Negative outcome reduces skill utility for that task type / query pattern.
   - Bounded adjustments prevent runaway oscillation and require minimum sample
     counts before heavy shifts.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.contracts.verification import VerificationStatus
from app.engine.skills.errors import SkillValidationError


def _compute_task_fingerprint(task_type: str, objective: str) -> str:
    normalized = f"{task_type.strip().lower()}::{' '.join(objective.strip().lower().split())}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SkillRetrievalObservation:
    """Record of a skill retrieval decision."""

    task_fingerprint: str
    task_type: str
    retrieved_skill_ids: tuple[str, ...]
    selected_skill_id: str | None
    agent_id: str | None
    execution_id: str
    task_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.task_fingerprint.strip():
            raise SkillValidationError("task_fingerprint must not be blank")
        if not self.task_type.strip():
            raise SkillValidationError("task_type must not be blank")
        if not self.execution_id.strip():
            raise SkillValidationError("execution_id must not be blank")


@dataclass(frozen=True)
class SkillRetrievalFeedback:
    """Verified outcome attributed to a prior skill retrieval decision."""

    task_fingerprint: str
    task_type: str
    skill_id: str
    verification_status: VerificationStatus
    agent_id: str | None
    execution_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_positive(self) -> bool:
        return self.verification_status is VerificationStatus.PASSED

    @property
    def is_negative(self) -> bool:
        return self.verification_status is VerificationStatus.FAILED


@dataclass(frozen=True)
class SkillRetrievalUtility:
    """Bounded utility adjustments for a (skill_id, task_type) pair."""

    skill_id: str
    task_type: str
    sample_count: int
    success_count: int
    failure_count: int
    utility_adjustment: float  # Bounded in [-0.5, +0.5]


class SkillAdaptiveRAGTracker:
    """Tracks retrieval observations and computes outcome-grounded utility updates."""

    def __init__(
        self,
        learning_rate: float = 0.1,
        max_positive_adjustment: float = 0.4,
        max_negative_adjustment: float = 0.4,
        min_sample_threshold: int = 1,
    ) -> None:
        self.learning_rate = learning_rate
        self.max_positive_adjustment = max_positive_adjustment
        self.max_negative_adjustment = max_negative_adjustment
        self.min_sample_threshold = min_sample_threshold
        self._observations: list[SkillRetrievalObservation] = []
        self._feedback: list[SkillRetrievalFeedback] = []

    def record_observation(
        self,
        task_type: str,
        objective: str,
        retrieved_skill_ids: list[str],
        selected_skill_id: str | None,
        agent_id: str | None,
        execution_id: str,
        task_id: str,
    ) -> SkillRetrievalObservation:
        obs = SkillRetrievalObservation(
            task_fingerprint=_compute_task_fingerprint(task_type, objective),
            task_type=task_type,
            retrieved_skill_ids=tuple(retrieved_skill_ids),
            selected_skill_id=selected_skill_id,
            agent_id=agent_id,
            execution_id=execution_id,
            task_id=task_id,
        )
        self._observations.append(obs)
        return obs

    def record_feedback(
        self,
        task_type: str,
        objective: str,
        skill_id: str,
        verification_status: VerificationStatus,
        agent_id: str | None,
        execution_id: str,
    ) -> SkillRetrievalFeedback:
        fb = SkillRetrievalFeedback(
            task_fingerprint=_compute_task_fingerprint(task_type, objective),
            task_type=task_type,
            skill_id=skill_id,
            verification_status=verification_status,
            agent_id=agent_id,
            execution_id=execution_id,
        )
        self._feedback.append(fb)
        return fb

    def get_utility_adjustment(self, skill_id: str, task_type: str) -> float:
        """Compute the bounded score adjustment factor for a skill on a task type."""
        relevant_fb = [
            f for f in self._feedback if f.skill_id == skill_id and f.task_type == task_type
        ]
        if len(relevant_fb) < self.min_sample_threshold:
            return 0.0

        successes = sum(1 for f in relevant_fb if f.is_positive)
        failures = sum(1 for f in relevant_fb if f.is_negative)
        conclusive = successes + failures
        if conclusive == 0:
            return 0.0

        # Empirical signal in [-1.0, 1.0]
        # At 50% success -> 0.0 adjustment
        # At 100% success -> +max_positive_adjustment
        # At 0% success -> -max_negative_adjustment
        raw_rate = successes / conclusive
        signal = (raw_rate - 0.5) * 2.0

        if signal >= 0.0:
            return signal * self.max_positive_adjustment
        else:
            return signal * self.max_negative_adjustment

    def get_all_feedback(self) -> list[SkillRetrievalFeedback]:
        return list(self._feedback)

    def get_all_observations(self) -> list[SkillRetrievalObservation]:
        return list(self._observations)


__all__ = [
    "SkillAdaptiveRAGTracker",
    "SkillRetrievalFeedback",
    "SkillRetrievalObservation",
    "SkillRetrievalUtility",
]
