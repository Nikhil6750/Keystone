"""Deterministic unit tests for CandidateSkillFoundry and Deduplication."""

from pathlib import Path

from app.contracts.enums import AgentCapability
from app.contracts.skills import SkillCategory, SkillStatus
from app.engine.skills.evidence import InMemorySkillEvidenceRepository
from app.engine.skills.foundry import CandidateSkillFoundry
from app.engine.skills.registry import SkillRegistry
from app.engine.skills.vault import ObsidianSkillVault


def test_candidate_skill_proposal_and_deduplication(tmp_path: Path) -> None:
    registry = SkillRegistry()
    evidence_repo = InMemorySkillEvidenceRepository()
    vault = ObsidianSkillVault(vault_root=tmp_path / "Vault")
    foundry = CandidateSkillFoundry(registry=registry, evidence_repo=evidence_repo, vault=vault)

    # 1. Propose candidate skill with 2 origin executions
    proposal, msg = foundry.propose_candidate_skill(
        skill_id="node-test-generation",
        name="Node Test Generation",
        description="Generates Jest test suites for Node.js services",
        category=SkillCategory.TESTING,
        task_types=("test_generation", "unit_testing"),
        capabilities=(AgentCapability.CODE_GENERATION, AgentCapability.TEST_EXECUTION),
        languages=("javascript", "typescript"),
        frameworks=("jest",),
        procedure="1. Identify exported functions\n2. Mock dependencies\n3. Write test specs",
        verification_contract={"criteria": ["npm test passes"]},
        origin_execution_ids=("exec-001", "exec-002"),
    )
    assert proposal is not None
    assert proposal.skill_id == "node-test-generation"
    assert len(foundry.list_proposals()) == 1

    # 2. Duplicate detection: Attempting to propose an identical / overlapping skill fails
    dup_prop, dup_msg = foundry.propose_candidate_skill(
        skill_id="node-test-gen-duplicate",
        name="Node Test Generation",
        description="Duplicate",
        category=SkillCategory.TESTING,
        task_types=("test_generation", "unit_testing"),
        capabilities=(AgentCapability.CODE_GENERATION,),
        languages=("javascript",),
        frameworks=("jest",),
        procedure="procedure",
        verification_contract={},
        origin_execution_ids=("exec-003", "exec-004"),
    )
    # The first one hasn't been approved into the registry yet, so approve it first
    skill = foundry.approve_proposal(proposal.proposal_id)
    assert skill.status == SkillStatus.CANDIDATE
    assert registry.get_skill("node-test-generation").status == SkillStatus.CANDIDATE

    # Now duplicate attempt will be detected against registry
    dup_prop_2, dup_msg_2 = foundry.propose_candidate_skill(
        skill_id="node-test-gen-duplicate",
        name="Node Test Generation",
        description="Duplicate",
        category=SkillCategory.TESTING,
        task_types=("test_generation", "unit_testing"),
        capabilities=(AgentCapability.CODE_GENERATION,),
        languages=("javascript",),
        frameworks=("jest",),
        procedure="procedure",
        verification_contract={},
        origin_execution_ids=("exec-003", "exec-004"),
    )
    assert dup_prop_2 is None
    assert "Duplicate detected" in dup_msg_2


def test_candidate_skill_rejection() -> None:
    registry = SkillRegistry()
    evidence_repo = InMemorySkillEvidenceRepository()
    foundry = CandidateSkillFoundry(registry=registry, evidence_repo=evidence_repo)

    proposal, _ = foundry.propose_candidate_skill(
        skill_id="flaky-candidate",
        name="Flaky Candidate",
        description="Proposal that will be rejected",
        category=SkillCategory.GENERAL,
        task_types=("misc",),
        capabilities=(AgentCapability.CODE_GENERATION,),
        languages=(),
        frameworks=(),
        procedure="procedure",
        verification_contract={},
        origin_execution_ids=("e-1", "e-2"),
    )
    assert proposal is not None
    assert len(foundry.list_proposals()) == 1

    # Reject proposal
    foundry.reject_proposal(proposal.proposal_id, reason="Low quality procedure")
    assert len(foundry.list_proposals()) == 0
