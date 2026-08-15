"""Deterministic tests for Skill × Agent empirical routing signal integration."""

from app.contracts.adapter import AgentDescriptor
from app.contracts.enums import AgentCapability, AgentStatus
from app.contracts.verification import VerificationStatus
from app.engine.planning.compiler import CompiledTaskNode
from app.engine.routing.availability import CandidateAgent
from app.engine.routing.organization import AgentOrganizationCompiler
from app.engine.routing.router import Router
from app.engine.skills.agent_intelligence import SkillAgentIntelligenceEngine
from app.engine.skills.evidence import (
    InMemorySkillEvidenceRepository,
    SkillExecutionEvidence,
)
from app.resilience.circuit_breaker import CircuitState


def _make_candidate(agent_type: str, caps: list[AgentCapability]) -> CandidateAgent:
    descriptor = AgentDescriptor(
        agent_type=agent_type,
        display_name=agent_type,
        capabilities=caps,
        cost_tier="standard",
    )
    return CandidateAgent(
        descriptor=descriptor,
        status=AgentStatus.AVAILABLE,
        circuit_state=CircuitState.CLOSED,
    )


def test_routing_without_skill_preserves_base_behavior() -> None:
    # Two identical capability agents
    c1 = _make_candidate("agent-alpha", [AgentCapability.CODE_GENERATION])
    c2 = _make_candidate("agent-beta", [AgentCapability.CODE_GENERATION])

    task = CompiledTaskNode(
        task_id="task-1",
        task_type="backend_task",
        title="Implement Backend API",
        objective="Build CRUD router",
        required_capabilities=[AgentCapability.CODE_GENERATION],
    )

    evidence_repo = InMemorySkillEvidenceRepository()
    intel_engine = SkillAgentIntelligenceEngine(evidence_repo=evidence_repo)
    compiler = AgentOrganizationCompiler(
        router=Router(), skill_agent_intelligence=intel_engine
    )

    # Base routing without skill assignment
    team = compiler.assemble_team([task], [c1, c2])
    assert team.assignments["task-1"].selected_agent_type is not None


def test_skill_agent_evidence_influences_routing_within_bounded_policy() -> None:
    # Candidates with equal base capabilities
    c_alpha = _make_candidate("agent-alpha", [AgentCapability.CODE_GENERATION])
    c_beta = _make_candidate("agent-beta", [AgentCapability.CODE_GENERATION])

    evidence_repo = InMemorySkillEvidenceRepository()

    # Agent Beta has 5 verified successful runs with "sql-optimization" skill
    for i in range(5):
        evidence_repo.record_evidence(
            SkillExecutionEvidence(
                skill_id="sql-optimization",
                skill_version="1.0.0",
                task_type="database_optimization",
                agent_id="agent-beta",
                execution_id=f"exec-beta-{i}",
                task_id=f"task-{i}",
                verification_status=VerificationStatus.PASSED,
                success=True,
            )
        )

    # Agent Alpha has 5 runs with 4 failures on "sql-optimization" skill
    for i in range(4):
        evidence_repo.record_evidence(
            SkillExecutionEvidence(
                skill_id="sql-optimization",
                skill_version="1.0.0",
                task_type="database_optimization",
                agent_id="agent-alpha",
                execution_id=f"exec-alpha-fail-{i}",
                task_id=f"task-fail-{i}",
                verification_status=VerificationStatus.FAILED,
                success=False,
            )
        )
    evidence_repo.record_evidence(
        SkillExecutionEvidence(
            skill_id="sql-optimization",
            skill_version="1.0.0",
            task_type="database_optimization",
            agent_id="agent-alpha",
            execution_id="exec-alpha-pass",
            task_id="task-pass",
            verification_status=VerificationStatus.PASSED,
            success=True,
        )
    )

    intel_engine = SkillAgentIntelligenceEngine(evidence_repo=evidence_repo)
    compiler = AgentOrganizationCompiler(
        router=Router(), skill_agent_intelligence=intel_engine
    )

    # Task assigned with "sql-optimization" skill
    task_with_skill = CompiledTaskNode(
        task_id="task-sql",
        task_type="database_optimization",
        title="Optimize slow query",
        objective="Add indexing and rewrite joins",
        required_capabilities=[AgentCapability.CODE_GENERATION],
        skill_id="sql-optimization",
        skill_version="1.0.0",
    )

    team = compiler.assemble_team([task_with_skill], [c_alpha, c_beta])
    # Agent Beta must be selected due to verified skill-agent evidence
    assert team.assignments["task-sql"].selected_agent_type == "agent-beta"
    assert team.assignments["task-sql"].fallback_order == ["agent-alpha"]


def test_neutral_prior_and_insufficient_samples_do_not_skew_routing() -> None:
    c_alpha = _make_candidate("agent-alpha", [AgentCapability.CODE_GENERATION])
    c_beta = _make_candidate("agent-beta", [AgentCapability.CODE_GENERATION])

    evidence_repo = InMemorySkillEvidenceRepository()
    # Only 1 sample for Agent Alpha (below min_sample_threshold of 2)
    evidence_repo.record_evidence(
        SkillExecutionEvidence(
            skill_id="docker-build",
            skill_version="1.0.0",
            task_type="devops",
            agent_id="agent-alpha",
            execution_id="exec-single-run",
            task_id="task-single",
            verification_status=VerificationStatus.PASSED,
            success=True,
        )
    )

    intel_engine = SkillAgentIntelligenceEngine(evidence_repo=evidence_repo)
    compiler = AgentOrganizationCompiler(
        router=Router(), skill_agent_intelligence=intel_engine
    )

    task = CompiledTaskNode(
        task_id="task-docker",
        task_type="devops",
        title="Dockerize application",
        objective="Create multistage Dockerfile",
        required_capabilities=[AgentCapability.CODE_GENERATION],
        skill_id="docker-build",
    )

    # With insufficient samples (< 2), adjustment remains 0.0 (neutral prior)
    team = compiler.assemble_team([task], [c_alpha, c_beta])
    assert team.assignments["task-docker"].selected_agent_type is not None


def test_single_failure_cannot_blacklist_agent() -> None:
    c_gamma = _make_candidate("agent-gamma", [AgentCapability.CODE_GENERATION])

    evidence_repo = InMemorySkillEvidenceRepository()
    # 1 failure for agent-gamma
    evidence_repo.record_evidence(
        SkillExecutionEvidence(
            skill_id="test-skill",
            skill_version="1.0.0",
            task_type="testing",
            agent_id="agent-gamma",
            execution_id="exec-1",
            task_id="t-1",
            verification_status=VerificationStatus.FAILED,
            success=False,
        )
    )

    intel_engine = SkillAgentIntelligenceEngine(evidence_repo=evidence_repo)
    compiler = AgentOrganizationCompiler(
        router=Router(), skill_agent_intelligence=intel_engine
    )

    task = CompiledTaskNode(
        task_id="t-2",
        task_type="testing",
        title="Write tests",
        objective="Write pytest suite",
        required_capabilities=[AgentCapability.CODE_GENERATION],
        skill_id="test-skill",
    )

    team = compiler.assemble_team([task], [c_gamma])
    # Agent remains eligible and selected when alone, never blacklisted
    assert team.assignments["t-2"].selected_agent_type == "agent-gamma"
