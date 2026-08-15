"""Stage 9C Configurable Skill Promotion & Degradation Policy."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SkillPromotionPolicy:
    """Configurable thresholds for skill lifecycle progression and degradation."""

    # DRAFT -> CANDIDATE
    require_structural_validation: bool = True

    # CANDIDATE -> VERIFIED
    min_verified_successes_for_verification: int = 3
    max_severe_failures_allowed_for_verification: int = 0

    # VERIFIED -> TRUSTED
    min_samples_for_trusted: int = 10
    min_reliability_for_trusted: float = 0.85

    # TRUSTED Degradation / Demotion
    trusted_degradation_failure_count: int = 3
    min_reliability_before_demotion: float = 0.70

    # Priors for smoothed reliability computation
    prior_alpha: float = 1.0
    prior_beta: float = 1.0


DEFAULT_SKILL_POLICY = SkillPromotionPolicy()

__all__ = ["DEFAULT_SKILL_POLICY", "SkillPromotionPolicy"]
