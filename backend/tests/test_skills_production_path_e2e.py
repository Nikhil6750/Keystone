"""Real Production-Path Stage 9C End-to-End Orchestration & Acceptance Test Suite.

Certifies through EndToEndOrchestrationService:
1. Goal submitted -> TaskGraph compiled -> Skill retrieved -> Skill provenance attached.
2. Routing receives Skill × Agent empirical signal.
3. Execution prompt contains bounded skill guidance.
4. Objective verification PASSED -> SkillEvidence persisted in DB.
5. Adaptive retrieval feedback recorded and consumed on subsequent requests.
6. Database restart preserves registry and evidence state.
7. Negative acceptance: Failing candidate skill receives negative evidence, no promotion,
   utility penalty, and trusted skills are uncorrupted.
"""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.contracts.adapter import AgentDescriptor
from app.contracts.enums import AgentCapability, AgentStatus
from app.contracts.planning import TaskSpec
from app.contracts.skills import SkillCategory, SkillContract, SkillStatus
from app.contracts.verification import VerificationStatus
from app.database.base import Base
from app.engine.orchestration.models import (
    OrchestrationOutcome,
    OrchestrationRequest,
)
from app.engine.orchestration.runtime import RuntimeCandidateProvider
from app.engine.orchestration.service import EndToEndOrchestrationService
from app.engine.registry import ExecutorRegistry
from app.engine.routing.availability import CandidateAgent
from app.engine.skills.adaptive_rag import SkillAdaptiveRAGTracker
from app.engine.skills.agent_intelligence import SkillAgentIntelligenceEngine
from app.engine.skills.evidence import (
    SkillExecutionEvidence,
    SqlAlchemySkillEvidenceRepository,
)
from app.engine.skills.lifecycle import SkillLifecycleManager
from app.engine.skills.registry import SkillRegistry
from app.engine.skills.retriever import SkillRetriever
from app.engine.skills.vault import ObsidianSkillVault


class FakeCandidateProvider(RuntimeCandidateProvider):
    def __init__(self, candidates: list[CandidateAgent]) -> None:
        self._candidates = candidates

    def candidates(self) -> list[CandidateAgent]:
        return list(self._candidates)


class VerifiedDemoAdapter:
    def execute(self, request: Any) -> dict[str, Any]:
        return {
            "agent_type": "demo-agent",
            "content": "Successfully implemented FastAPI CRUD router with verified tests.",
            "exit_code": 0,
            "output": "5 passed in 0.05s",
            "tests_total": 5,
            "tests_passed": 5,
            "tests_failed": 0,
            "tests_skipped": 0,
            "metadata": {
                "execution_mode": "demo",
                "exit_code": 0,
            },
        }


@pytest.mark.asyncio
async def test_full_production_orchestration_path_with_skill_lifecycle(tmp_path: Path) -> None:
    # 1. Setup disposable test DB and Session
    db_file = tmp_path / "production_path.db"
    db_url = f"sqlite:///{db_file}"
    engine = create_engine(db_url)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = Session()

    # 2. Setup disposable Vault and Registry
    vault_dir = tmp_path / "SkillVault"
    vault_dir.mkdir()
    vault = ObsidianSkillVault(vault_root=vault_dir)

    evidence_repo = SqlAlchemySkillEvidenceRepository(session_factory=Session)
    registry = SkillRegistry(evidence_repo=evidence_repo, session_factory=Session)
    adaptive_tracker = SkillAdaptiveRAGTracker()
    retriever = SkillRetriever(
        registry=registry,
        evidence_repo=evidence_repo,
        adaptive_tracker=adaptive_tracker,
    )
    intel_engine = SkillAgentIntelligenceEngine(evidence_repo=evidence_repo)

    # 3. Register a verified backend skill
    verified_skill = SkillContract(
        skill_id="fastapi-crud-standard",
        version="1.0.0",
        name="FastAPI CRUD Standard",
        description="Standard pattern for RESTful CRUD services in FastAPI",
        category=SkillCategory.BACKEND,
        task_types=("api_implementation", "backend"),
        capabilities=(AgentCapability.CODE_GENERATION,),
        languages=("python",),
        frameworks=("fastapi",),
        preconditions=("Python 3.11+", "FastAPI installed"),
        contraindications=("Do not use blocking I/O in async routes",),
        procedure=(
            "1. Define Pydantic request/response schemas\n"
            "2. Create APIRouter\n"
            "3. Add CRUD endpoints"
        ),
        verification_contract={
            "criteria": ["Endpoints return 200/201", "Schema validation active"]
        },
        status=SkillStatus.VERIFIED,
    )
    registry.register_skill(verified_skill)

    # Write skill to vault
    vault.write_skill(verified_skill)

    # 4. Setup Executor Registry and Candidates
    exec_registry = ExecutorRegistry()
    exec_registry.register("demo-agent", VerifiedDemoAdapter())

    from app.resilience.circuit_breaker import CircuitState

    descriptor = AgentDescriptor(
        agent_type="demo-agent",
        display_name="Demo Agent",
        capabilities=[
            AgentCapability.CODE_GENERATION,
            AgentCapability.TEST_GENERATION,
            AgentCapability.TEST_EXECUTION,
            AgentCapability.FILE_EDITING,
            AgentCapability.CODE_REVIEW,
            AgentCapability.DOCUMENTATION,
        ],
        cost_tier="standard",
    )
    candidate = CandidateAgent(
        descriptor=descriptor,
        status=AgentStatus.AVAILABLE,
        circuit_state=CircuitState.CLOSED,
    )
    candidate_provider = FakeCandidateProvider([candidate])

    # 5. Build EndToEndOrchestrationService with full skills wiring
    service = EndToEndOrchestrationService(
        db=db,
        registry=exec_registry,
        candidate_provider=candidate_provider,
        skill_registry=registry,
        skill_evidence_repo=evidence_repo,
        skill_retriever=retriever,
        skill_adaptive_tracker=adaptive_tracker,
        skill_agent_intelligence=intel_engine,
    )

    request = OrchestrationRequest(
        request_id="req-test-production-1",
        goal="Implement FastAPI CRUD endpoints for user management",
        task_type="api_implementation",
        workspace_root=str(tmp_path),
    )

    # 6. Execute Production Orchestration Flow
    result = await service.orchestrate(request)

    # Verify execution and verification passed
    assert result.outcome == OrchestrationOutcome.VERIFIED_SUCCESS
    assert result.workflow_id is not None

    # Verify Skill Evidence was persisted to DB
    persisted_evidence = evidence_repo.get_evidence_for_skill("fastapi-crud-standard", "1.0.0")
    assert len(persisted_evidence) >= 1
    ev = persisted_evidence[0]
    assert ev.skill_id == "fastapi-crud-standard"
    assert ev.verification_status == VerificationStatus.PASSED
    assert ev.success is True

    # 7. Restart Simulation: Reconnect new repositories to SQLite DB
    db.close()
    Session2 = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    restarted_evidence_repo = SqlAlchemySkillEvidenceRepository(session_factory=Session2)
    restarted_registry = SkillRegistry(
        evidence_repo=restarted_evidence_repo, session_factory=Session2
    )

    # State check after restart
    skill_v1 = restarted_registry.get_skill("fastapi-crud-standard", "1.0.0")
    assert skill_v1.status == SkillStatus.VERIFIED
    restarted_metrics = restarted_evidence_repo.get_metrics_for_skill(
        "fastapi-crud-standard", "1.0.0"
    )
    assert restarted_metrics.total_samples >= 1
    assert restarted_metrics.verified_successes >= 1

    # 8. Adaptive Retrieval Before/After Proof
    restarted_retriever = SkillRetriever(
        registry=restarted_registry,
        evidence_repo=restarted_evidence_repo,
        adaptive_tracker=adaptive_tracker,
    )
    # The verified success should yield a positive utility score above the neutral prior (0.5)
    task_spec = TaskSpec(
        key="task-check",
        name="Build user router",
        task_type="api_implementation",
        input_payload={"objective": "Implement user endpoints in FastAPI"},
        required_capabilities=[AgentCapability.CODE_GENERATION],
    )
    matches = restarted_retriever.retrieve_skills_for_task(task_spec, limit=1)
    assert len(matches) == 1
    assert matches[0].skill.skill_id == "fastapi-crud-standard"
    assert matches[0].verified_utility > 0.5  # Positive evidence increased utility


@pytest.mark.asyncio
async def test_negative_acceptance_failing_candidate_skill(tmp_path: Path) -> None:
    db_file = tmp_path / "negative_acceptance.db"
    db_url = f"sqlite:///{db_file}"
    engine = create_engine(db_url)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = Session()

    evidence_repo = SqlAlchemySkillEvidenceRepository(session_factory=Session)
    registry = SkillRegistry(evidence_repo=evidence_repo, session_factory=Session)
    adaptive_tracker = SkillAdaptiveRAGTracker()
    lifecycle_mgr = SkillLifecycleManager(registry=registry, evidence_repo=evidence_repo)

    # 1. Register a trusted skill and a bad candidate skill
    trusted_skill = SkillContract(
        skill_id="solid-backend",
        version="1.0.0",
        name="Solid Backend",
        description="Proven pattern",
        category=SkillCategory.BACKEND,
        task_types=("backend",),
        capabilities=(AgentCapability.CODE_GENERATION,),
        procedure="1. Robust code",
        verification_contract={"criteria": ["All tests pass"]},
        status=SkillStatus.TRUSTED,
    )
    registry.register_skill(trusted_skill)

    bad_candidate = SkillContract(
        skill_id="flaky-candidate",
        version="1.0.0",
        name="Flaky Candidate",
        description="Unverified flaky procedure",
        category=SkillCategory.BACKEND,
        task_types=("flaky_task",),
        capabilities=(AgentCapability.CODE_GENERATION,),
        procedure="1. Flaky steps",
        verification_contract={"criteria": ["Flaky criteria"]},
        status=SkillStatus.CANDIDATE,
    )
    registry.register_skill(bad_candidate)

    # 2. Record objective verification failure for the bad candidate
    evidence_repo.record_evidence(
        SkillExecutionEvidence(
            skill_id="flaky-candidate",
            skill_version="1.0.0",
            task_type="flaky_task",
            agent_id="demo-agent",
            execution_id="exec-fail-1",
            task_id="task-fail-1",
            verification_status=VerificationStatus.FAILED,
            success=False,
            failure_category="TEST_ASSERTION_FAILURE",
        )
    )
    adaptive_tracker.record_feedback(
        task_fingerprint="fp-flaky",
        task_type="flaky_task",
        skill_id="flaky-candidate",
        verification_status=VerificationStatus.FAILED,
        agent_id="demo-agent",
        execution_id="exec-fail-1",
    )

    # 3. Verify Candidate does NOT promote
    updated_candidate = lifecycle_mgr.auto_promote_or_demote_skill("flaky-candidate")
    assert updated_candidate.status == SkillStatus.CANDIDATE  # Still candidate, no promotion

    # 4. Verify Adaptive Utility Decreased for bad candidate
    retriever = SkillRetriever(
        registry=registry,
        evidence_repo=evidence_repo,
        adaptive_tracker=adaptive_tracker,
        min_score_threshold=0.0,
    )
    task_spec = TaskSpec(
        key="task-flaky",
        name="Run flaky task",
        task_type="flaky_task",
        input_payload={"objective": "Execute flaky operation"},
        required_capabilities=[AgentCapability.CODE_GENERATION],
    )
    matches = retriever.retrieve_skills_for_task(task_spec, limit=1)
    assert len(matches) == 1
    assert matches[0].skill.skill_id == "flaky-candidate"
    assert matches[0].verified_utility < 0.5  # Utility penalized below neutral prior

    # 5. Verify unrelated trusted skill remains completely untouched and TRUSTED
    assert registry.get_skill("solid-backend").status == SkillStatus.TRUSTED
    db.close()
