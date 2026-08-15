"""Stage 9C Skill Adaptive Retrieval Adapter.

Thin skill-specific adapter integrating Skill Foundry retrieval with Keystone's
Stage 7.5 `app.engine.adaptive_retrieval` infrastructure.

Architecture:
    SkillRetriever / SkillOrchestrationCoordinator
          |
    RetrievalObservation (models.py / compute_query_fingerprint)
          |
    Execution & Objective Verification (VerificationStatus.PASSED / FAILED)
          |
    RetrievalFeedback (feedback.py / RetrievalFeedbackRepository)
          |
    RetrievalPassport (passport.py / rebuild_retrieval_passport)
          |
    Evidence Hierarchy & Bounded Scoring (scoring.py / select_evidence / bounded_adjustment)
          |
    Future SkillRetriever Scoring (bounded learned utility in [-0.15, +0.15])
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.contracts.enums import AgentExecutionStatus
from app.contracts.verification import VerificationStatus
from app.engine.adaptive_retrieval.errors import (
    MalformedRetrievalFeedbackError,
)
from app.engine.adaptive_retrieval.feedback import (
    InMemoryRetrievalFeedbackRepository,
    RetrievalFeedback,
    RetrievalFeedbackRepository,
)
from app.engine.adaptive_retrieval.models import (
    RetrievalObservation,
    compute_query_fingerprint,
)
from app.engine.adaptive_retrieval.passport import (
    RetrievalPassport,
    rebuild_retrieval_passport,
)
from app.engine.adaptive_retrieval.policy import AdaptiveRetrievalPolicy
from app.engine.adaptive_retrieval.scoring import (
    SelectedEvidence,
    bounded_adjustment,
    select_evidence,
)
from app.engine.benchmark_learning.models import EvidenceSource
from app.engine.learning.aggregation import MIN_SAMPLE_SIZE_FOR_CONFIDENCE

if TYPE_CHECKING:
    from app.engine.skills.evidence import SkillEvidenceRepository


def _compute_task_fingerprint(task_type: str, objective: str) -> str:
    """Compute query fingerprint using Stage 7.5 normalized sha256."""
    return compute_query_fingerprint(f"{task_type} {objective}")


@dataclass(frozen=True)
class SkillRetrievalUtility:
    """Explainability snapshot of learned utility for a skill."""

    skill_id: str
    task_type: str | None
    sample_count: int
    success_count: int
    failure_count: int
    utility_adjustment: float
    evidence: SelectedEvidence


class SkillAdaptiveRetrievalAdapter:
    """Translates skill retrieval events into Stage 7.5 adaptive_retrieval models

    and computes bounded utility adjustments using existing passport and scoring.
    """

    def __init__(
        self,
        feedback_repo: RetrievalFeedbackRepository | None = None,
        policy: AdaptiveRetrievalPolicy | None = None,
        evidence_repo: SkillEvidenceRepository | None = None,
        repository_id: str | None = None,
    ) -> None:
        self._feedback_repo: RetrievalFeedbackRepository = (
            feedback_repo or InMemoryRetrievalFeedbackRepository()
        )
        self._policy: AdaptiveRetrievalPolicy = policy or AdaptiveRetrievalPolicy(
            enabled=True,
            minimum_verified_samples=MIN_SAMPLE_SIZE_FOR_CONFIDENCE,
            max_positive_adjustment=0.15,
            max_negative_adjustment=0.15,
            allow_production_evidence=True,
            allow_benchmark_evidence=False,
        )
        self._evidence_repo = evidence_repo
        self._repository_id = repository_id
        self._observations: list[RetrievalObservation] = []

        # Sync existing durable DB evidence if repository is provided
        if self._evidence_repo is not None:
            self.sync_from_evidence_repo()

    @property
    def policy(self) -> AdaptiveRetrievalPolicy:
        return self._policy

    @property
    def feedback_repo(self) -> RetrievalFeedbackRepository:
        return self._feedback_repo

    def sync_from_evidence_repo(self) -> int:
        """Rehydrate feedback repository from durable SkillEvidenceRepository."""
        if self._evidence_repo is None:
            return 0
        count = 0
        for ev in self._evidence_repo.get_all_evidence():
            retrieval_id = f"retrieval::skill::{ev.task_type}::{ev.skill_id}"
            try:
                fb = RetrievalFeedback(
                    retrieval_id=retrieval_id,
                    chunk_ids=(ev.skill_id,),
                    verification_status=ev.verification_status,
                    task_type=ev.task_type,
                    repository_id=self._repository_id,
                    agent_type=ev.agent_id,
                    evidence_source=EvidenceSource.PRODUCTION,
                    execution_id=ev.execution_id,
                    created_at=ev.timestamp,
                )
                self._feedback_repo.add(fb)
                count += 1
            except Exception:
                pass
        return count

    def record_observation(
        self,
        task_type: str,
        objective: str = "",
        retrieved_skill_ids: tuple[str, ...] | list[str] = (),
        selected_skill_id: str | None = None,
        agent_id: str | None = None,
        execution_id: str = "exec-default",
        task_id: str = "",
        task_fingerprint: str | None = None,
    ) -> RetrievalObservation:
        """Record a retrieval decision using Stage 7.5 RetrievalObservation."""
        retrieved_tuple: tuple[str, ...] = tuple(retrieved_skill_ids)
        selected_tuple: tuple[str, ...]
        if selected_skill_id and selected_skill_id in retrieved_tuple:
            selected_tuple = (selected_skill_id,)
        elif selected_skill_id:
            # Preserve invariant: selected_chunk_ids subset of retrieved_chunk_ids
            retrieved_tuple = retrieved_tuple + (selected_skill_id,)
            selected_tuple = (selected_skill_id,)
        else:
            selected_tuple = ()

        n = len(retrieved_tuple)
        original_ranks = tuple(range(1, n + 1))
        original_scores = tuple(max(0.0, 1.0 - (i * 0.1)) for i in range(n))
        chunk_hashes = tuple(f"hash::{cid}" for cid in retrieved_tuple)

        query_fp = task_fingerprint or _compute_task_fingerprint(task_type, objective)

        obs = RetrievalObservation(
            query_fingerprint=query_fp,
            task_type=task_type,
            repository_id=self._repository_id,
            agent_type=agent_id,
            retrieved_chunk_ids=retrieved_tuple,
            retrieved_chunk_content_hashes=chunk_hashes,
            original_ranks=original_ranks,
            original_scores=original_scores,
            selected_chunk_ids=selected_tuple,
            created_at=datetime.now(UTC),
        )
        self._observations.append(obs)
        return obs

    def record_feedback(
        self,
        task_type: str,
        objective: str = "",
        skill_id: str = "",
        verification_status: VerificationStatus = VerificationStatus.PASSED,
        agent_id: str | None = None,
        execution_id: str = "exec-default",
        task_fingerprint: str | None = None,
        repository_id: str | None = None,
        execution_status: AgentExecutionStatus | None = AgentExecutionStatus.SUCCEEDED,
    ) -> RetrievalFeedback:
        """Record verified outcome using Stage 7.5 RetrievalFeedback."""
        if not skill_id or not skill_id.strip():
            raise MalformedRetrievalFeedbackError("skill_id must not be blank")
        if not execution_id or not execution_id.strip():
            execution_id = f"exec::{datetime.now(UTC).timestamp()}"

        query_fp = task_fingerprint or _compute_task_fingerprint(task_type, objective)
        repo_id = repository_id or self._repository_id

        retrieval_id = f"retrieval::{query_fp}::{task_type}::{repo_id or ''}::{skill_id}"

        fb = RetrievalFeedback(
            retrieval_id=retrieval_id,
            chunk_ids=(skill_id,),
            verification_status=verification_status,
            task_type=task_type,
            repository_id=repo_id,
            agent_type=agent_id,
            execution_status=execution_status,
            evidence_source=EvidenceSource.PRODUCTION,
            execution_id=execution_id,
            created_at=datetime.now(UTC),
        )
        self._feedback_repo.add(fb)
        return fb

    def get_passport_for_skill(self, skill_id: str) -> RetrievalPassport:
        """Rebuild Stage 7.5 RetrievalPassport for a skill from raw feedback."""
        all_feedback = self._feedback_repo.all()
        return rebuild_retrieval_passport(all_feedback, chunk_id=skill_id)

    def get_utility_adjustment(
        self,
        skill_id: str,
        task_type: str | None = None,
        repository_id: str | None = None,
    ) -> float:
        """Compute bounded utility adjustment using Stage 7.5 passport and scoring."""
        all_feedback = self._feedback_repo.all()
        if not all_feedback and self._evidence_repo is not None:
            self.sync_from_evidence_repo()
            all_feedback = self._feedback_repo.all()

        passport = rebuild_retrieval_passport(all_feedback, chunk_id=skill_id)
        repo_id = repository_id or self._repository_id

        evidence = select_evidence(
            production_passport=passport,
            benchmark_passport=None,
            task_type=task_type,
            repository_id=repo_id,
            policy=self._policy,
        )
        return bounded_adjustment(evidence, policy=self._policy)

    def get_utility_breakdown(
        self,
        skill_id: str,
        task_type: str | None = None,
        repository_id: str | None = None,
    ) -> SkillRetrievalUtility:
        """Explainable breakdown of utility calculation."""
        passport = self.get_passport_for_skill(skill_id)
        repo_id = repository_id or self._repository_id

        evidence = select_evidence(
            production_passport=passport,
            benchmark_passport=None,
            task_type=task_type,
            repository_id=repo_id,
            policy=self._policy,
        )
        adj = bounded_adjustment(evidence, policy=self._policy)
        bucket = evidence.bucket
        if bucket is not None:
            sample_cnt = bucket.verification.verification_sample_count
            succ_cnt = bucket.verification.verified_success_count
            fail_cnt = bucket.verification.verification_failure_count
        else:
            sample_cnt = passport.overall.verification.verification_sample_count
            succ_cnt = passport.overall.verification.verified_success_count
            fail_cnt = passport.overall.verification.verification_failure_count

        return SkillRetrievalUtility(
            skill_id=skill_id,
            task_type=task_type,
            sample_count=sample_cnt,
            success_count=succ_cnt,
            failure_count=fail_cnt,
            utility_adjustment=adj,
            evidence=evidence,
        )

    def get_all_feedback(self) -> list[RetrievalFeedback]:
        return self._feedback_repo.all()

    def get_all_observations(self) -> list[RetrievalObservation]:
        return list(self._observations)


# Alias for backward compatibility across Stage 9C modules
SkillAdaptiveRAGTracker = SkillAdaptiveRetrievalAdapter

__all__ = [
    "SkillAdaptiveRAGTracker",
    "SkillAdaptiveRetrievalAdapter",
    "SkillRetrievalUtility",
    "_compute_task_fingerprint",
]
