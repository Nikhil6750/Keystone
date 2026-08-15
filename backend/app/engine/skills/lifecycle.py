"""Stage 9C Skill Lifecycle Manager.

Evaluates skill lifecycle transitions purely from objective execution evidence
and the configured SkillPromotionPolicy.

Lifecycle:
DRAFT -> CANDIDATE -> VERIFIED -> TRUSTED -> DEPRECATED

Key Invariant:
Models/agents MUST NOT promote skills by self-reporting "this worked".
Promotion evaluates objective VerificationStatus.PASSED events recorded in SkillEvidence.
"""

from app.contracts.skills import SkillContract, SkillStatus
from app.engine.skills.evidence import SkillEvidenceRepository, SkillMetricsSummary
from app.engine.skills.policy import DEFAULT_SKILL_POLICY, SkillPromotionPolicy
from app.engine.skills.registry import SkillRegistry


class SkillLifecycleManager:
    """Manages evaluation and transitions of skill lifecycle states."""

    def __init__(
        self,
        registry: SkillRegistry,
        evidence_repo: SkillEvidenceRepository,
        policy: SkillPromotionPolicy = DEFAULT_SKILL_POLICY,
    ) -> None:
        self.registry = registry
        self.evidence_repo = evidence_repo
        self.policy = policy

    def evaluate_skill_lifecycle(
        self, skill_id: str, version: str | None = None
    ) -> tuple[SkillStatus, str]:
        """Evaluate the appropriate lifecycle status for a skill based on evidence and policy.

        Returns (recommended_status, reason).
        """
        skill = self.registry.get_skill(skill_id, version)
        metrics: SkillMetricsSummary = self.evidence_repo.get_metrics_for_skill(
            skill_id, skill.version
        )

        current = skill.status

        # If explicitly deprecated by human, remain deprecated unless re-instated
        if current == SkillStatus.DEPRECATED:
            return SkillStatus.DEPRECATED, "Skill is deprecated"

        # Check DRAFT
        if current == SkillStatus.DRAFT:
            if not skill.procedure or not skill.name:
                return SkillStatus.DRAFT, "Skill missing basic procedure or name"
            if metrics.total_samples == 0:
                return (
                    SkillStatus.CANDIDATE,
                    "Validated structure, ready for evaluation as candidate",
                )

        # Check CANDIDATE
        if current in (SkillStatus.DRAFT, SkillStatus.CANDIDATE):
            min_succ = self.policy.min_verified_successes_for_verification
            max_severe = self.policy.max_severe_failures_allowed_for_verification
            if (
                metrics.verified_successes >= min_succ
                and metrics.severe_failures <= max_severe
            ):
                return (
                    SkillStatus.VERIFIED,
                    f"Passed objective verification in {metrics.verified_successes} "
                    f"real executions with {metrics.severe_failures} severe failures",
                )
            return (
                SkillStatus.CANDIDATE,
                f"Candidate status: {metrics.verified_successes}/{min_succ} "
                "required verified successes",
            )

        # Check VERIFIED
        if current == SkillStatus.VERIFIED:
            conclusive = metrics.verified_successes + metrics.verified_failures
            if conclusive >= self.policy.min_samples_for_trusted:
                reliability = metrics.smoothed_reliability(
                    prior_alpha=self.policy.prior_alpha, prior_beta=self.policy.prior_beta
                )
                if reliability >= self.policy.min_reliability_for_trusted:
                    return (
                        SkillStatus.TRUSTED,
                        f"Achieved trusted status: {conclusive} samples with "
                        f"{reliability:.1%} smoothed reliability",
                    )
            return (
                SkillStatus.VERIFIED,
                f"Verified status: {conclusive}/{self.policy.min_samples_for_trusted} "
                "samples for trusted",
            )

        # Check TRUSTED (Degradation checks)
        if current == SkillStatus.TRUSTED:
            conclusive = metrics.verified_successes + metrics.verified_failures
            if metrics.verified_failures >= self.policy.trusted_degradation_failure_count:
                reliability = metrics.smoothed_reliability(
                    prior_alpha=self.policy.prior_alpha, prior_beta=self.policy.prior_beta
                )
                if reliability < self.policy.min_reliability_before_demotion:
                    return (
                        SkillStatus.VERIFIED,
                        f"Degraded performance: {metrics.verified_failures} failures observed, "
                        f"smoothed reliability dropped to {reliability:.1%} "
                        f"(below {self.policy.min_reliability_before_demotion:.1%} threshold)",
                    )
            is_severely_degraded = (
                metrics.verified_failures >= (self.policy.trusted_degradation_failure_count * 2)
                and metrics.verified_failures > metrics.verified_successes
            )
            if is_severely_degraded:
                return SkillStatus.DEPRECATED, "Severely degraded: persistent verification failures"
            return SkillStatus.TRUSTED, "Trusted performance criteria maintained"

        return current, f"Current status {current.value} maintained"

    def auto_promote_or_demote_skill(
        self, skill_id: str, version: str | None = None
    ) -> SkillContract:
        """Evaluate and apply lifecycle transition to a skill."""
        skill = self.registry.get_skill(skill_id, version)
        new_status, reason = self.evaluate_skill_lifecycle(skill_id, version)

        if new_status != skill.status:
            return self.registry.update_skill_status(skill_id, new_status, version)
        return skill

    def human_deprecate_skill(self, skill_id: str, version: str | None = None) -> SkillContract:
        """Explicitly deprecate a skill via human command."""
        return self.registry.update_skill_status(skill_id, SkillStatus.DEPRECATED, version)


__all__ = ["SkillLifecycleManager"]
