"""Stage 9C Multi-Factor Skill Retriever.

Retrieves and ranks skills for a TaskGraph node using multi-factor scoring:
    score = (
        semantic_relevance
        * capability_match
        * task_type_match
        * project_relevance
        * verified_utility
        * freshness
    )

Uses bounded neutral priors so new candidate/draft skills remain discoverable.
Does not rely only on vector similarity.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.contracts.planning import TaskSpec
from app.contracts.skills import SkillContract, SkillStatus
from app.engine.planning.compiler import CompiledTaskNode
from app.engine.skills.adaptive_rag import SkillAdaptiveRAGTracker
from app.engine.skills.evidence import SkillEvidenceRepository
from app.engine.skills.registry import SkillRegistry


@dataclass(frozen=True)
class SkillMatchScore:
    """Detailed score breakdown for explainability."""

    skill: SkillContract
    total_score: float
    semantic_relevance: float
    capability_match: float
    task_type_match: float
    project_relevance: float
    verified_utility: float
    freshness: float
    status_bonus: float
    explanation: str


def _tokenize_text(text: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[A-Za-z0-9_\-]+", text) if len(w) > 2}


def _jaccard_similarity(tokens1: set[str], tokens2: set[str]) -> float:
    if not tokens1 or not tokens2:
        return 0.0
    intersection = len(tokens1 & tokens2)
    union = len(tokens1 | tokens2)
    return intersection / union if union > 0 else 0.0


class SkillRetriever:
    """Multi-factor skill retrieval engine with adaptive outcome-grounded learning."""

    def __init__(
        self,
        registry: SkillRegistry,
        evidence_repo: SkillEvidenceRepository | None = None,
        adaptive_tracker: SkillAdaptiveRAGTracker | None = None,
        min_score_threshold: float = 0.05,
    ) -> None:
        self.registry = registry
        self.evidence_repo = evidence_repo
        self.adaptive_tracker = adaptive_tracker
        self.min_score_threshold = min_score_threshold

    def retrieve_skills_for_task(
        self,
        task: CompiledTaskNode | TaskSpec,
        workspace_context: dict[str, Any] | None = None,
        limit: int = 5,
    ) -> list[SkillMatchScore]:
        """Rank and return the top skills matching the given task."""
        # 1. Gather task metadata
        if isinstance(task, CompiledTaskNode):
            task_type = task.task_type
            title = task.title
            objective = task.objective
            required_caps = set(task.required_capabilities)
        else:
            task_type = task.task_type
            title = task.name
            objective = (task.input_payload or {}).get("objective", task.name)
            required_caps = set(task.required_capabilities or [])

        task_text = f"{title} {objective} {task_type}"
        task_tokens = _tokenize_text(task_text)

        workspace_languages = set(
            (workspace_context or {}).get("languages", [])
        )
        workspace_frameworks = set(
            (workspace_context or {}).get("frameworks", [])
        )

        all_skills = self.registry.list_skills(latest_only=True)
        scored_skills: list[SkillMatchScore] = []

        for skill in all_skills:
            if not skill.is_eligible_for_retrieval():
                continue

            # 1. Task Type Match
            if task_type in skill.task_types:
                task_type_match = 1.0
            elif not skill.task_types:
                task_type_match = 0.5  # General skill
            else:
                skill_tt_tokens = {t.lower() for t in skill.task_types}
                has_partial_match = any(
                    task_type.lower() in st or st in task_type.lower() for st in skill_tt_tokens
                )
                task_type_match = 0.75 if has_partial_match else 0.2

            # 2. Capability Match
            if not required_caps:
                capability_match = 0.8
            else:
                skill_caps = set(skill.capabilities)
                if required_caps.issubset(skill_caps):
                    capability_match = 1.0
                elif required_caps & skill_caps:
                    overlap_ratio = len(required_caps & skill_caps) / len(required_caps)
                    capability_match = 0.5 + 0.5 * overlap_ratio
                else:
                    capability_match = 0.3

            # 3. Semantic Relevance
            skill_text = (
                f"{skill.name} {skill.description} "
                f"{' '.join(skill.task_types)} {skill.procedure}"
            )
            skill_tokens = _tokenize_text(skill_text)
            jaccard = _jaccard_similarity(task_tokens, skill_tokens)
            semantic_relevance = min(1.0, max(0.2, jaccard * 3.0 + 0.2))

            # 4. Project / Workspace Relevance (languages & frameworks)
            proj_rel = 0.5
            if skill.languages or skill.frameworks:
                lang_match = True
                if workspace_languages and skill.languages:
                    skill_langs = {lang.lower() for lang in skill.languages}
                    ws_langs = {lang.lower() for lang in workspace_languages}
                    lang_match = bool(skill_langs & ws_langs)

                fw_match = True
                if workspace_frameworks and skill.frameworks:
                    skill_fws = {fw.lower() for fw in skill.frameworks}
                    ws_fws = {fw.lower() for fw in workspace_frameworks}
                    fw_match = bool(skill_fws & ws_fws)

                if lang_match and fw_match:
                    proj_rel = 1.0
                elif lang_match or fw_match:
                    proj_rel = 0.75
                else:
                    proj_rel = 0.3

            # 5. Verified Utility (Empirical Reliability + Adaptive RAG Adjustment)
            verified_utility = 0.5  # Neutral baseline prior
            if self.evidence_repo is not None:
                metrics = self.evidence_repo.get_metrics_for_skill(skill.skill_id)
                if metrics.total_samples > 0:
                    verified_utility = metrics.smoothed_reliability(
                        prior_alpha=1.0, prior_beta=1.0
                    )

            if self.adaptive_tracker is not None:
                adj = self.adaptive_tracker.get_utility_adjustment(skill.skill_id, task_type)
                verified_utility = min(1.0, max(0.1, verified_utility + adj))

            # 6. Status Bonus / Multiplier
            status_multipliers = {
                SkillStatus.TRUSTED: 1.2,
                SkillStatus.VERIFIED: 1.1,
                SkillStatus.CANDIDATE: 0.95,
                SkillStatus.DRAFT: 0.85,
                SkillStatus.DEPRECATED: 0.0,
            }
            status_bonus = status_multipliers.get(skill.status, 0.8)

            # 7. Bounded Timestamp Freshness (bounded in [0.85, 1.0] based on updated_at)
            now = datetime.now(UTC)
            updated_dt = skill.updated_at
            if updated_dt.tzinfo is None:
                updated_dt = updated_dt.replace(tzinfo=UTC)
            age_days = max(0.0, (now - updated_dt).total_seconds() / 86400.0)
            freshness = max(0.85, 1.0 - 0.15 * min(1.0, age_days / 90.0))

            # Composite Score calculation
            base_score = (
                semantic_relevance
                * capability_match
                * task_type_match
                * proj_rel
                * verified_utility
                * freshness
                * status_bonus
            )

            explanation = (
                f"Status: {skill.status.value}, TaskTypeMatch: {task_type_match:.2f}, "
                f"CapMatch: {capability_match:.2f}, Semantic: {semantic_relevance:.2f}, "
                f"Utility: {verified_utility:.2f}, Freshness: {freshness:.2f}"
            )

            if base_score >= self.min_score_threshold:
                scored_skills.append(
                    SkillMatchScore(
                        skill=skill,
                        total_score=base_score,
                        semantic_relevance=semantic_relevance,
                        capability_match=capability_match,
                        task_type_match=task_type_match,
                        project_relevance=proj_rel,
                        verified_utility=verified_utility,
                        freshness=freshness,
                        status_bonus=status_bonus,
                        explanation=explanation,
                    )
                )

        # Sort descending by total score
        scored_skills.sort(key=lambda s: -s.total_score)
        return scored_skills[:limit]


__all__ = ["SkillMatchScore", "SkillRetriever"]
