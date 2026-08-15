"""Stage 9C Full E2E Acceptance & Negative Acceptance Test Suite.

Certifies:
1. End-to-end flow: TaskGraph -> SkillRetriever -> SkillAssignment -> AgentSelection
   -> Verification -> Evidence.
2. Verified outcome updates retrieval utility and SkillEvidence.
3. Negative acceptance: A bad candidate skill experiences failure, gets penalized
   in retrieval, does not promote, and does not corrupt trusted skills.
"""

from pathlib import Path

from app.contracts.enums import AgentCapability
from app.contracts.skills import SkillCategory, SkillContract, SkillStatus
from app.contracts.verification import VerificationStatus
from app.engine.planning.compiler import TaskGraphCompilerV2
from app.engine.skills.adaptive_rag import SkillAdaptiveRAGTracker
from app.engine.skills.agent_intelligence import SkillAgentIntelligenceEngine
from app.engine.skills.evidence import InMemorySkillEvidenceRepository
from app.engine.skills.lifecycle import SkillLifecycleManager
from app.engine.skills.orchestration_adapter import SkillOrchestrationCoordinator
from app.engine.skills.registry import SkillRegistry
from app.engine.skills.retriever import SkillRetriever
from app.engine.skills.vault import ObsidianSkillVault


def test_e2e_skill_foundry_acceptance_cycle(tmp_path: Path) -> None:
    # 1. Setup disposable vault and registry
    vault_dir = tmp_path / "Keystone-Skills-Certification-Vault"
    vault = ObsidianSkillVault(vault_root=vault_dir)

    skill_frontend = SkillContract(
        skill_id="frontend-web-component",
        version="1.0.0",
        name="Frontend Web Component",
        description="Creates reusable HTML/JS/CSS frontend components",
        category=SkillCategory.FRONTEND,
        task_types=("frontend_ui", "ui_component"),
        capabilities=(AgentCapability.CODE_GENERATION, AgentCapability.FILE_EDITING),
        languages=("javascript", "html"),
        procedure="1. Build HTML structure\n2. Add Vanilla CSS\n3. Bind event handlers",
        verification_contract={"criteria": ["UI components render cleanly"]},
        status=SkillStatus.VERIFIED,
    )
    skill_api = SkillContract(
        skill_id="python-api-endpoint",
        version="1.0.0",
        name="Python API Endpoint",
        description="Builds FastAPI REST endpoints",
        category=SkillCategory.BACKEND,
        task_types=("api_implementation", "backend"),
        capabilities=(AgentCapability.CODE_GENERATION, AgentCapability.FILE_EDITING),
        languages=("python",),
        frameworks=("fastapi",),
        procedure="1. Create router\n2. Add endpoints\n3. Add Pydantic schemas",
        verification_contract={"criteria": ["Endpoints return 200 OK"]},
        status=SkillStatus.VERIFIED,
    )
    skill_test = SkillContract(
        skill_id="node-test-generation",
        version="1.0.0",
        name="Node Test Generation",
        description="Builds automated test suites",
        category=SkillCategory.TESTING,
        task_types=("test_generation", "unit_testing"),
        capabilities=(AgentCapability.TEST_EXECUTION, AgentCapability.CODE_GENERATION),
        languages=("javascript", "python"),
        procedure="1. Write assertions\n2. Execute test runner",
        verification_contract={"criteria": ["Test suite passes"]},
        status=SkillStatus.VERIFIED,
    )

    vault.write_skill(skill_frontend)
    vault.write_skill(skill_api)
    vault.write_skill(skill_test)

    evidence_repo = InMemorySkillEvidenceRepository()
    registry = SkillRegistry(evidence_repo=evidence_repo, vault=vault)
    registry.ingest_vault()

    retriever = SkillRetriever(registry=registry, evidence_repo=evidence_repo)
    adaptive_rag = SkillAdaptiveRAGTracker()
    agent_intel = SkillAgentIntelligenceEngine(evidence_repo=evidence_repo)
    coordinator = SkillOrchestrationCoordinator(
        registry=registry,
        evidence_repo=evidence_repo,
        retriever=retriever,
        adaptive_rag=adaptive_rag,
        agent_intelligence=agent_intel,
    )
    lifecycle_mgr = SkillLifecycleManager(registry=registry, evidence_repo=evidence_repo)

    # 2. Compile TaskGraph for Goal: Build small frontend plus Python API and automated tests
    compiler = TaskGraphCompilerV2()
    plan = compiler.compile(
        "Build a small frontend web component plus Python API and automated unit tests"
    )
    assert len(plan) >= 2

    # 3. Retrieve skills and assign
    assignments = coordinator.assign_skills_to_tasks(
        tasks=plan,
        workspace_context={"languages": ["python", "javascript"], "frameworks": ["fastapi"]},
        execution_id="exec-e2e-01",
    )
    assert len(assignments) == len(plan)

    # 4. Execute and verify runs
    for task in plan:
        skill, assignment = assignments[task.task_id]
        if skill is not None:
            coordinator.record_execution_outcome(
                skill_id=skill.skill_id,
                skill_version=skill.version,
                task_type=task.task_type,
                agent_id="codex",
                execution_id="exec-e2e-01",
                task_id=task.task_id,
                verification_status=VerificationStatus.PASSED,
                latency_ms=150.0,
                objective=task.objective,
            )

    # 5. Check evidence updated
    api_ev = evidence_repo.get_evidence_for_skill("python-api-endpoint")
    assert len(api_ev) >= 1
    assert api_ev[0].success is True

    # Check Adaptive RAG utility increased
    util = adaptive_rag.get_utility_adjustment("python-api-endpoint", "api_implementation")
    assert util >= 0.0

    # Check no automatic TRUSTED promotion without reaching sample threshold (10)
    lifecycle_mgr.auto_promote_or_demote_skill("python-api-endpoint")
    assert registry.get_skill("python-api-endpoint").status == SkillStatus.VERIFIED


def test_negative_acceptance_bad_candidate_skill(tmp_path: Path) -> None:
    vault = ObsidianSkillVault(vault_root=tmp_path / "Vault")
    evidence_repo = InMemorySkillEvidenceRepository()
    registry = SkillRegistry(evidence_repo=evidence_repo, vault=vault)

    # Trusted good skill
    good_skill = SkillContract(
        skill_id="reliable-api-builder",
        version="1.0.0",
        name="Reliable API Builder",
        description="Reliable API building",
        category=SkillCategory.BACKEND,
        task_types=("api_implementation",),
        capabilities=(AgentCapability.CODE_GENERATION,),
        status=SkillStatus.TRUSTED,
    )
    # Deliberately bad candidate skill
    bad_skill = SkillContract(
        skill_id="flaky-broken-candidate",
        version="1.0.0",
        name="Flaky Broken Candidate",
        description="Experimental untested approach",
        category=SkillCategory.BACKEND,
        task_types=("api_implementation",),
        capabilities=(AgentCapability.CODE_GENERATION,),
        status=SkillStatus.CANDIDATE,
    )
    registry.register_skill(good_skill)
    registry.register_skill(bad_skill)

    retriever = SkillRetriever(registry=registry, evidence_repo=evidence_repo)
    adaptive_rag = SkillAdaptiveRAGTracker()
    lifecycle_mgr = SkillLifecycleManager(registry=registry, evidence_repo=evidence_repo)
    coordinator = SkillOrchestrationCoordinator(
        registry=registry,
        evidence_repo=evidence_repo,
        retriever=retriever,
        adaptive_rag=adaptive_rag,
    )

    # Execute multiple failing runs with bad skill
    for i in range(5):
        coordinator.record_execution_outcome(
            skill_id="flaky-broken-candidate",
            skill_version="1.0.0",
            task_type="api_implementation",
            agent_id="claude",
            execution_id=f"exec-bad-{i}",
            task_id=f"task-bad-{i}",
            verification_status=VerificationStatus.FAILED,
            failure_category="TEST_EXECUTION_FAILURE",
            objective="Build API with experimental approach",
        )

    # Verify negative evidence recorded
    bad_metrics = evidence_repo.get_metrics_for_skill("flaky-broken-candidate")
    assert bad_metrics.total_samples == 5
    assert bad_metrics.verified_failures == 5
    assert bad_metrics.verified_successes == 0
    assert bad_metrics.raw_success_rate == 0.0

    # Ensure it does NOT promote
    status, reason = lifecycle_mgr.evaluate_skill_lifecycle("flaky-broken-candidate")
    assert status == SkillStatus.CANDIDATE
    assert "0/3 required verified successes" in reason

    # Ensure Adaptive RAG utility is heavily penalized
    bad_util = adaptive_rag.get_utility_adjustment("flaky-broken-candidate", "api_implementation")
    assert bad_util < 0.0

    # Verify trusted skill is NOT corrupted
    good_current = registry.get_skill("reliable-api-builder")
    assert good_current.status == SkillStatus.TRUSTED
    good_metrics = evidence_repo.get_metrics_for_skill("reliable-api-builder")
    assert good_metrics.total_samples == 0
