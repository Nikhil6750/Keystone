"""Stage 9C Skill × Agent Intelligence.

Learns empirical performance of (Skill, Agent) and (Skill, Agent, TaskType) combinations
from verified execution evidence.

Key invariants:
- NO hardcoded provider preferences.
- Bayesian smoothed prior for low sample counts:
    prior_score = 0.5 (neutral)
    smoothed = (successes + alpha * prior_score) / (total_conclusive + alpha)
- One success cannot dominate scoring (e.g. 1/1 gives ~0.67 with alpha=2.0, not 1.0).
- One failure cannot permanently suppress an agent (e.g. 0/1 gives ~0.33 with alpha=2.0, not 0.0).
- Provides an explainable agent-skill alignment score in [0.0, 1.0].
"""

from dataclasses import dataclass

from app.contracts.verification import VerificationStatus
from app.engine.skills.evidence import SkillEvidenceRepository


@dataclass(frozen=True)
class SkillAgentPerformance:
    """Aggregated performance of a specific agent using a specific skill."""

    skill_id: str
    agent_id: str
    total_runs: int
    verified_successes: int
    verified_failures: int
    mean_latency_ms: float
    recovery_count: int

    @property
    def raw_success_rate(self) -> float | None:
        conclusive = self.verified_successes + self.verified_failures
        if conclusive == 0:
            return None
        return self.verified_successes / conclusive

    def empirical_score(self, prior_weight: float = 2.0, prior_mean: float = 0.5) -> float:
        """Returns a Bayesian-smoothed score in [0.0, 1.0].

        With 0 samples, returns prior_mean (0.5).
        With 1 success, returns (1 + 2*0.5)/(1 + 2) = 2/3 = 0.67.
        With 1 failure, returns (0 + 2*0.5)/(1 + 2) = 1/3 = 0.33.
        With 20 successes / 0 failures, returns (20 + 1)/(20 + 2) = 21/22 = 0.954.
        """
        conclusive = self.verified_successes + self.verified_failures
        return (self.verified_successes + prior_weight * prior_mean) / (conclusive + prior_weight)


class SkillAgentIntelligenceEngine:
    """Computes skill-agent empirical metrics and scoring adjustments."""

    def __init__(
        self,
        evidence_repo: SkillEvidenceRepository,
        prior_weight: float = 2.0,
        prior_mean: float = 0.5,
    ) -> None:
        self._evidence_repo = evidence_repo
        self._prior_weight = prior_weight
        self._prior_mean = prior_mean

    def get_agent_skill_performance(
        self, skill_id: str, agent_id: str
    ) -> SkillAgentPerformance:
        all_evidence = self._evidence_repo.get_evidence_for_skill(skill_id)
        matching = [e for e in all_evidence if e.agent_id == agent_id]

        if not matching:
            return SkillAgentPerformance(
                skill_id=skill_id,
                agent_id=agent_id,
                total_runs=0,
                verified_successes=0,
                verified_failures=0,
                mean_latency_ms=0.0,
                recovery_count=0,
            )

        total = len(matching)
        successes = sum(
            1 for e in matching if e.verification_status is VerificationStatus.PASSED
        )
        failures = sum(
            1 for e in matching if e.verification_status is VerificationStatus.FAILED
        )
        mean_lat = sum(e.latency_ms for e in matching) / total if total > 0 else 0.0
        recoveries = sum(1 for e in matching if e.recovery_required)

        return SkillAgentPerformance(
            skill_id=skill_id,
            agent_id=agent_id,
            total_runs=total,
            verified_successes=successes,
            verified_failures=failures,
            mean_latency_ms=mean_lat,
            recovery_count=recoveries,
        )

    def compute_agent_skill_score(self, skill_id: str, agent_id: str) -> float:
        """Returns the empirical score in [0.0, 1.0] for the agent-skill pair."""
        perf = self.get_agent_skill_performance(skill_id, agent_id)
        return perf.empirical_score(
            prior_weight=self._prior_weight, prior_mean=self._prior_mean
        )

    def rank_agents_for_skill(
        self, skill_id: str, candidate_agent_ids: list[str]
    ) -> list[tuple[str, float, SkillAgentPerformance]]:
        """Rank candidate agents for a skill by empirical score descending."""
        scored = []
        for agent_id in candidate_agent_ids:
            perf = self.get_agent_skill_performance(skill_id, agent_id)
            score = perf.empirical_score(
                prior_weight=self._prior_weight, prior_mean=self._prior_mean
            )
            scored.append((agent_id, score, perf))

        # Sort descending by score, then total_runs, then agent_id
        scored.sort(key=lambda x: (-x[1], -x[2].total_runs, x[0]))
        return scored


__all__ = [
    "SkillAgentIntelligenceEngine",
    "SkillAgentPerformance",
]
