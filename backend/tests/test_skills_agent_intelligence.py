"""Deterministic unit tests for Skill × Agent Intelligence."""

from app.contracts.verification import VerificationStatus
from app.engine.skills.agent_intelligence import (
    SkillAgentIntelligenceEngine,
)
from app.engine.skills.evidence import (
    InMemorySkillEvidenceRepository,
    SkillExecutionEvidence,
)


def test_agent_skill_matrix_learning_and_neutral_priors() -> None:
    repo = InMemorySkillEvidenceRepository()
    engine = SkillAgentIntelligenceEngine(evidence_repo=repo, prior_weight=2.0, prior_mean=0.5)

    # 1. 0 runs for 'claude' on 'fastapi-crud' -> returns exactly neutral prior (0.5)
    score_0 = engine.compute_agent_skill_score(skill_id="fastapi-crud", agent_id="claude")
    assert score_0 == 0.5

    # 2. Record 20 runs for 'codex' (19 successes, 1 failure) -> 95% raw
    for i in range(19):
        repo.record_evidence(
            SkillExecutionEvidence(
                skill_id="fastapi-crud",
                skill_version="1.0.0",
                task_type="api",
                agent_id="codex",
                execution_id=f"e-codex-{i}",
                task_id=f"t-{i}",
                verification_status=VerificationStatus.PASSED,
                success=True,
            )
        )
    repo.record_evidence(
        SkillExecutionEvidence(
            skill_id="fastapi-crud",
            skill_version="1.0.0",
            task_type="api",
            agent_id="codex",
            execution_id="e-codex-19",
            task_id="t-19",
            verification_status=VerificationStatus.FAILED,
            success=False,
        )
    )

    # 3. Record 15 runs for 'claude' (14 successes, 1 failure) -> 93.3% raw
    for i in range(14):
        repo.record_evidence(
            SkillExecutionEvidence(
                skill_id="fastapi-crud",
                skill_version="1.0.0",
                task_type="api",
                agent_id="claude",
                execution_id=f"e-claude-{i}",
                task_id=f"t-{i}",
                verification_status=VerificationStatus.PASSED,
                success=True,
            )
        )
    repo.record_evidence(
        SkillExecutionEvidence(
            skill_id="fastapi-crud",
            skill_version="1.0.0",
            task_type="api",
            agent_id="claude",
            execution_id="e-claude-14",
            task_id="t-14",
            verification_status=VerificationStatus.FAILED,
            success=False,
        )
    )

    # 4. Record 8 runs for 'antigravity' (7 successes, 1 failure) -> 87.5% raw
    for i in range(7):
        repo.record_evidence(
            SkillExecutionEvidence(
                skill_id="fastapi-crud",
                skill_version="1.0.0",
                task_type="api",
                agent_id="antigravity",
                execution_id=f"e-agy-{i}",
                task_id=f"t-{i}",
                verification_status=VerificationStatus.PASSED,
                success=True,
            )
        )
    repo.record_evidence(
        SkillExecutionEvidence(
            skill_id="fastapi-crud",
            skill_version="1.0.0",
            task_type="api",
            agent_id="antigravity",
            execution_id="e-agy-7",
            task_id="t-7",
            verification_status=VerificationStatus.FAILED,
            success=False,
        )
    )

    # Check scores
    score_codex = engine.compute_agent_skill_score("fastapi-crud", "codex")
    score_claude = engine.compute_agent_skill_score("fastapi-crud", "claude")
    score_agy = engine.compute_agent_skill_score("fastapi-crud", "antigravity")

    assert score_codex > score_claude > score_agy

    # Rank agents for skill
    ranked = engine.rank_agents_for_skill("fastapi-crud", ["antigravity", "codex", "claude"])
    assert [r[0] for r in ranked] == ["codex", "claude", "antigravity"]


def test_one_success_does_not_dominate_and_one_failure_does_not_suppress() -> None:
    repo = InMemorySkillEvidenceRepository()
    engine = SkillAgentIntelligenceEngine(evidence_repo=repo, prior_weight=2.0, prior_mean=0.5)

    # Agent A has 1 run, 1 success -> score = (1 + 2*0.5)/(1 + 2) = 2/3 ≈ 0.667
    repo.record_evidence(
        SkillExecutionEvidence(
            skill_id="test-skill",
            skill_version="1.0.0",
            task_type="api",
            agent_id="agent-a",
            execution_id="e-1",
            task_id="t-1",
            verification_status=VerificationStatus.PASSED,
            success=True,
        )
    )
    score_a = engine.compute_agent_skill_score("test-skill", "agent-a")
    assert abs(score_a - 0.6666) < 0.01

    # Agent B has 10 runs, 9 successes -> score = (9 + 1)/(10 + 2) = 10/12 ≈ 0.833
    for i in range(9):
        repo.record_evidence(
            SkillExecutionEvidence(
                skill_id="test-skill",
                skill_version="1.0.0",
                task_type="api",
                agent_id="agent-b",
                execution_id=f"e-b-{i}",
                task_id=f"t-{i}",
                verification_status=VerificationStatus.PASSED,
                success=True,
            )
        )
    repo.record_evidence(
        SkillExecutionEvidence(
            skill_id="test-skill",
            skill_version="1.0.0",
            task_type="api",
            agent_id="agent-b",
            execution_id="e-b-9",
            task_id="t-9",
            verification_status=VerificationStatus.FAILED,
            success=False,
        )
    )
    score_b = engine.compute_agent_skill_score("test-skill", "agent-b")
    # Agent B with 9/10 beats Agent A with 1/1 (1 success cannot dominate)
    assert score_b > score_a

    # Agent C has 1 run, 1 failure -> score = (0 + 1)/(1 + 2) = 1/3 ≈ 0.333
    # (not 0.0, remains discoverable/eligible)
    repo.record_evidence(
        SkillExecutionEvidence(
            skill_id="test-skill",
            skill_version="1.0.0",
            task_type="api",
            agent_id="agent-c",
            execution_id="e-c-1",
            task_id="t-1",
            verification_status=VerificationStatus.FAILED,
            success=False,
        )
    )
    score_c = engine.compute_agent_skill_score("test-skill", "agent-c")
    assert score_c > 0.0
    assert abs(score_c - 0.3333) < 0.01
