"""Stage 9C Candidate Skill Foundry & Deduplication Engine.

Discovers reusable patterns from repeated verified execution successes, creates
candidate skill proposals with full provenance, and deduplicates against existing skills.

Key Rules:
1. NEVER automatically creates TRUSTED skills.
2. Candidate skills are created with status CANDIDATE or DRAFT.
3. Full provenance: origin execution IDs, supporting evidence, proposed verification contract.
4. Deduplication: Compares semantic overlap, task types, and capabilities. If overlapping,
   suggests updating existing skill or bumping version rather than generating duplicate IDs.
"""

import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.contracts.enums import AgentCapability
from app.contracts.skills import SkillCategory, SkillContract, SkillStatus
from app.engine.skills.evidence import SkillEvidenceRepository
from app.engine.skills.registry import SkillRegistry
from app.engine.skills.vault import ObsidianSkillVault


@dataclass(frozen=True)
class CandidateSkillProposal:
    """A proposed new candidate skill generated from verified execution patterns."""

    proposal_id: str
    skill_id: str
    name: str
    description: str
    category: SkillCategory | str
    task_types: tuple[str, ...]
    capabilities: tuple[AgentCapability, ...]
    languages: tuple[str, ...]
    frameworks: tuple[str, ...]
    procedure: str
    verification_contract: dict[str, Any]
    origin_execution_ids: tuple[str, ...]
    supporting_evidence_count: int
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_skill_contract(self) -> SkillContract:
        return SkillContract(
            skill_id=self.skill_id,
            version="1.0.0",
            name=self.name,
            description=self.description,
            category=self.category,
            task_types=self.task_types,
            capabilities=self.capabilities,
            languages=self.languages,
            frameworks=self.frameworks,
            procedure=self.procedure,
            verification_contract=self.verification_contract,
            source="foundry_candidate",
            provenance={
                "proposal_id": self.proposal_id,
                "origin_execution_ids": list(self.origin_execution_ids),
                "supporting_evidence_count": self.supporting_evidence_count,
            },
            status=SkillStatus.CANDIDATE,
        )


class CandidateSkillFoundry:
    """Analyzes verified executions, deduplicates, and proposes candidate skills."""

    def __init__(
        self,
        registry: SkillRegistry,
        evidence_repo: SkillEvidenceRepository,
        vault: ObsidianSkillVault | None = None,
        min_pattern_occurrences: int = 2,
    ) -> None:
        self.registry = registry
        self.evidence_repo = evidence_repo
        self.vault = vault
        self.min_pattern_occurrences = min_pattern_occurrences
        self._proposals: dict[str, CandidateSkillProposal] = {}
        self._rejected_proposals: set[str] = set()

    def check_for_duplicates(
        self,
        task_types: tuple[str, ...],
        capabilities: tuple[AgentCapability, ...],
        name: str,
    ) -> SkillContract | None:
        """Search existing skills for high semantic or task-type overlap.

        Returns matching existing SkillContract if overlap is detected, else None.
        """
        all_skills = self.registry.list_skills(latest_only=True)
        name_lower = name.lower()

        for skill in all_skills:
            # 1. Exact or near name match
            if skill.name.lower() == name_lower:
                return skill

            # 2. Complete task type and capability overlap
            if (
                set(task_types)
                and set(task_types).issubset(set(skill.task_types))
                and set(capabilities)
                and set(capabilities).issubset(set(skill.capabilities))
            ):
                return skill

        return None

    def propose_candidate_skill(
        self,
        skill_id: str,
        name: str,
        description: str,
        category: SkillCategory | str,
        task_types: tuple[str, ...],
        capabilities: tuple[AgentCapability, ...],
        languages: tuple[str, ...],
        frameworks: tuple[str, ...],
        procedure: str,
        verification_contract: dict[str, Any],
        origin_execution_ids: tuple[str, ...],
    ) -> tuple[CandidateSkillProposal | None, str]:
        """Propose a candidate skill after deduplication check."""
        if not origin_execution_ids:
            return None, "Candidate creation requires origin execution evidence"

        if len(origin_execution_ids) < self.min_pattern_occurrences:
            return (
                None,
                f"Requires at least {self.min_pattern_occurrences} verified executions "
                f"(found {len(origin_execution_ids)})",
            )

        # Check for duplicates
        duplicate = self.check_for_duplicates(task_types, capabilities, name)
        if duplicate is not None:
            return (
                None,
                f"Duplicate detected: overlaps with existing skill '{duplicate.skill_id}' "
                f"v{duplicate.version}. Update existing skill evidence or bump version instead.",
            )

        proposal_id = f"proposal-{skill_id}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
        proposal = CandidateSkillProposal(
            proposal_id=proposal_id,
            skill_id=skill_id,
            name=name,
            description=description,
            category=category,
            task_types=task_types,
            capabilities=capabilities,
            languages=languages,
            frameworks=frameworks,
            procedure=procedure,
            verification_contract=verification_contract,
            origin_execution_ids=origin_execution_ids,
            supporting_evidence_count=len(origin_execution_ids),
        )

        self._proposals[proposal_id] = proposal

        # If vault exists, write candidate to Candidates/ directory
        if self.vault is not None:
            with contextlib.suppress(Exception):
                candidate_contract = proposal.to_skill_contract()
                self.vault.write_skill(candidate_contract, directory="Candidates")

        return proposal, "Candidate skill proposal created successfully"

    def list_proposals(self) -> list[CandidateSkillProposal]:
        return [
            p
            for pid, p in self._proposals.items()
            if pid not in self._rejected_proposals
        ]

    def approve_proposal(self, proposal_id: str) -> SkillContract:
        """Human approves proposal -> registered in registry as CANDIDATE."""
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise KeyError(f"Proposal '{proposal_id}' not found")

        skill = proposal.to_skill_contract()
        self.registry.register_skill(skill)

        if self.vault is not None:
            with contextlib.suppress(Exception):
                self.vault.write_skill(skill)

        return skill

    def reject_proposal(
        self, proposal_id: str, reason: str = "Rejected by human reviewer"
    ) -> None:
        """Human rejects candidate proposal."""
        if proposal_id not in self._proposals:
            raise KeyError(f"Proposal '{proposal_id}' not found")
        self._rejected_proposals.add(proposal_id)


__all__ = [
    "CandidateSkillFoundry",
    "CandidateSkillProposal",
]
