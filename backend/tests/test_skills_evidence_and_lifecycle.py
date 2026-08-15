"""Deterministic unit tests for SkillEvidence, metrics, and SkillLifecycleManager."""

from app.contracts.skills import SkillCategory, SkillContract, SkillStatus
from app.contracts.verification import VerificationStatus
from app.engine.skills.evidence import (
    InMemorySkillEvidenceRepository,
    SkillExecutionEvidence,
)
from app.engine.skills.lifecycle import SkillLifecycleManager
from app.engine.skills.policy import SkillPromotionPolicy
from app.engine.skills.registry import SkillRegistry


def test_evidence_objective_success_invariants() -> None:
    # 1. VerificationStatus.PASSED forces success=True
    ev_pass = SkillExecutionEvidence(
        skill_id="fastapi-crud",
        skill_version="1.0.0",
        task_type="api_implementation",
        agent_id="codex",
        execution_id="exec-1",
        task_id="task-1",
        verification_status=VerificationStatus.PASSED,
        success=False,  # Deliberately mismatched, must be corrected to True
    )
    assert ev_pass.success is True

    # 2. VerificationStatus.FAILED forces success=False
    ev_fail = SkillExecutionEvidence(
        skill_id="fastapi-crud",
        skill_version="1.0.0",
        task_type="api_implementation",
        agent_id="codex",
        execution_id="exec-2",
        task_id="task-2",
        verification_status=VerificationStatus.FAILED,
        success=True,  # Deliberately mismatched, must be corrected to False
    )
    assert ev_fail.success is False


def test_evidence_smoothed_reliability_neutral_priors() -> None:
    repo = InMemorySkillEvidenceRepository()

    # 0 samples -> smoothed reliability is exactly 0.5 (neutral prior)
    metrics_0 = repo.get_metrics_for_skill("new-skill")
    assert metrics_0.total_samples == 0
    assert metrics_0.raw_success_rate is None
    assert metrics_0.smoothed_reliability(prior_alpha=1.0, prior_beta=1.0) == 0.5

    # 1 success -> (1 + 1)/(1 + 2) = 2/3 ≈ 0.667 (bounded, not 1.0)
    repo.record_evidence(
        SkillExecutionEvidence(
            skill_id="new-skill",
            skill_version="1.0.0",
            task_type="api",
            agent_id="claude",
            execution_id="e-1",
            task_id="t-1",
            verification_status=VerificationStatus.PASSED,
            success=True,
        )
    )
    metrics_1 = repo.get_metrics_for_skill("new-skill")
    assert metrics_1.total_samples == 1
    assert metrics_1.raw_success_rate == 1.0
    assert abs(metrics_1.smoothed_reliability() - 0.6666) < 0.01

    # 1 failure -> (0 + 1)/(1 + 2) = 1/3 ≈ 0.333 (bounded, not 0.0)
    repo_fail = InMemorySkillEvidenceRepository()
    repo_fail.record_evidence(
        SkillExecutionEvidence(
            skill_id="fail-skill",
            skill_version="1.0.0",
            task_type="api",
            agent_id="claude",
            execution_id="e-2",
            task_id="t-2",
            verification_status=VerificationStatus.FAILED,
            success=False,
        )
    )
    metrics_fail = repo_fail.get_metrics_for_skill("fail-skill")
    assert metrics_fail.raw_success_rate == 0.0
    assert abs(metrics_fail.smoothed_reliability() - 0.3333) < 0.01


def test_skill_lifecycle_progression_and_degradation() -> None:
    registry = SkillRegistry()
    repo = InMemorySkillEvidenceRepository()
    policy = SkillPromotionPolicy(
        min_verified_successes_for_verification=3,
        max_severe_failures_allowed_for_verification=0,
        min_samples_for_trusted=10,
        min_reliability_for_trusted=0.85,
        min_reliability_before_demotion=0.70,
    )
    mgr = SkillLifecycleManager(registry=registry, evidence_repo=repo, policy=policy)

    skill = SkillContract(
        skill_id="fastapi-crud",
        version="1.0.0",
        name="FastAPI CRUD",
        description="CRUD endpoints",
        category=SkillCategory.BACKEND,
        status=SkillStatus.DRAFT,
        procedure="1. Step 1\n2. Step 2",
    )
    registry.register_skill(skill)

    # 1. DRAFT with 0 runs -> evaluates to CANDIDATE
    status, _ = mgr.evaluate_skill_lifecycle("fastapi-crud")
    assert status == SkillStatus.CANDIDATE
    mgr.auto_promote_or_demote_skill("fastapi-crud")
    assert registry.get_skill("fastapi-crud").status == SkillStatus.CANDIDATE

    # 2. CANDIDATE with 2 verified successes (under threshold 3) -> remains CANDIDATE
    for i in range(2):
        repo.record_evidence(
            SkillExecutionEvidence(
                skill_id="fastapi-crud",
                skill_version="1.0.0",
                task_type="api",
                agent_id="codex",
                execution_id=f"e-{i}",
                task_id=f"t-{i}",
                verification_status=VerificationStatus.PASSED,
                success=True,
            )
        )
    status, _ = mgr.evaluate_skill_lifecycle("fastapi-crud")
    assert status == SkillStatus.CANDIDATE

    # 3. 3rd verified success -> promotes to VERIFIED
    repo.record_evidence(
        SkillExecutionEvidence(
            skill_id="fastapi-crud",
            skill_version="1.0.0",
            task_type="api",
            agent_id="codex",
            execution_id="e-3",
            task_id="t-3",
            verification_status=VerificationStatus.PASSED,
            success=True,
        )
    )
    status, _ = mgr.evaluate_skill_lifecycle("fastapi-crud")
    assert status == SkillStatus.VERIFIED
    mgr.auto_promote_or_demote_skill("fastapi-crud")
    assert registry.get_skill("fastapi-crud").status == SkillStatus.VERIFIED

    # 4. Add up to 10 total samples (9 successes, 1 failure) -> promotes to TRUSTED
    # (reliability = (9+1)/(10+2) = 10/12 = 0.833)
    # With 11 successes, 0 failures -> (11+1)/(11+2) = 12/13 = 0.923 >= 0.85
    for i in range(4, 12):
        repo.record_evidence(
            SkillExecutionEvidence(
                skill_id="fastapi-crud",
                skill_version="1.0.0",
                task_type="api",
                agent_id="codex",
                execution_id=f"e-{i}",
                task_id=f"t-{i}",
                verification_status=VerificationStatus.PASSED,
                success=True,
            )
        )
    status, _ = mgr.evaluate_skill_lifecycle("fastapi-crud")
    assert status == SkillStatus.TRUSTED
    mgr.auto_promote_or_demote_skill("fastapi-crud")
    assert registry.get_skill("fastapi-crud").status == SkillStatus.TRUSTED

    # 5. Degradation: Add multiple failures so reliability drops below 0.70
    for i in range(12, 20):
        repo.record_evidence(
            SkillExecutionEvidence(
                skill_id="fastapi-crud",
                skill_version="1.0.0",
                task_type="api",
                agent_id="codex",
                execution_id=f"e-{i}",
                task_id=f"t-{i}",
                verification_status=VerificationStatus.FAILED,
                success=False,
            )
        )
    status, reason = mgr.evaluate_skill_lifecycle("fastapi-crud")
    assert status == SkillStatus.VERIFIED
    assert "Degraded performance" in reason
    mgr.auto_promote_or_demote_skill("fastapi-crud")
    assert registry.get_skill("fastapi-crud").status == SkillStatus.VERIFIED

    # 6. Human deprecation
    mgr.human_deprecate_skill("fastapi-crud")
    assert registry.get_skill("fastapi-crud").status == SkillStatus.DEPRECATED
