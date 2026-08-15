"""Deterministic unit tests for SkillRetriever and Outcome-Grounded Adaptive RAG."""

from app.contracts.enums import AgentCapability
from app.contracts.planning import TaskSpec
from app.contracts.skills import SkillCategory, SkillContract, SkillStatus
from app.contracts.verification import VerificationStatus
from app.engine.skills.adaptive_rag import SkillAdaptiveRAGTracker
from app.engine.skills.evidence import (
    InMemorySkillEvidenceRepository,
)
from app.engine.skills.registry import SkillRegistry
from app.engine.skills.retriever import SkillRetriever


def test_multi_factor_skill_retrieval_ranking() -> None:
    registry = SkillRegistry()
    repo = InMemorySkillEvidenceRepository()

    # Skill 1: FastAPI Backend
    s1 = SkillContract(
        skill_id="fastapi-crud-endpoint",
        version="1.0.0",
        name="FastAPI CRUD Endpoint",
        description="Creates RESTful FastAPI endpoints with Pydantic validation",
        category=SkillCategory.BACKEND,
        task_types=("api_implementation", "crud"),
        capabilities=(AgentCapability.CODE_GENERATION, AgentCapability.FILE_EDITING),
        languages=("python",),
        frameworks=("fastapi",),
        status=SkillStatus.TRUSTED,
    )
    # Skill 2: Node Express Backend
    s2 = SkillContract(
        skill_id="express-crud-endpoint",
        version="1.0.0",
        name="Express CRUD Endpoint",
        description="Creates Node Express REST endpoints",
        category=SkillCategory.BACKEND,
        task_types=("api_implementation", "crud"),
        capabilities=(AgentCapability.CODE_GENERATION, AgentCapability.FILE_EDITING),
        languages=("javascript", "typescript"),
        frameworks=("express",),
        status=SkillStatus.VERIFIED,
    )
    # Skill 3: React UI
    s3 = SkillContract(
        skill_id="react-frontend-component",
        version="1.0.0",
        name="React Component",
        description="Creates React frontend components",
        category=SkillCategory.FRONTEND,
        task_types=("frontend", "ui"),
        capabilities=(AgentCapability.CODE_GENERATION,),
        languages=("typescript",),
        frameworks=("react",),
        status=SkillStatus.TRUSTED,
    )
    registry.register_skill(s1)
    registry.register_skill(s2)
    registry.register_skill(s3)

    retriever = SkillRetriever(registry=registry, evidence_repo=repo)

    # Task asking for Python FastAPI implementation
    python_task = TaskSpec(
        key="task-api",
        name="Create User API",
        task_type="api_implementation",
        required_capabilities=[AgentCapability.CODE_GENERATION, AgentCapability.FILE_EDITING],
        input_payload={"objective": "Implement user endpoints using FastAPI"},
    )

    matches = retriever.retrieve_skills_for_task(
        task=python_task,
        workspace_context={"languages": ["python"], "frameworks": ["fastapi"]},
        limit=3,
    )

    assert len(matches) >= 2
    # Skill 1 (FastAPI + Python + Trusted) must rank #1
    assert matches[0].skill.skill_id == "fastapi-crud-endpoint"
    assert matches[0].total_score > matches[1].total_score


def test_new_skills_neutral_prior_discoverability() -> None:
    registry = SkillRegistry()
    repo = InMemorySkillEvidenceRepository()

    new_skill = SkillContract(
        skill_id="brand-new-candidate",
        version="1.0.0",
        name="Brand New Candidate Skill",
        description="Untested candidate skill for GraphQL APIs",
        category=SkillCategory.BACKEND,
        task_types=("graphql_api",),
        capabilities=(AgentCapability.CODE_GENERATION,),
        status=SkillStatus.CANDIDATE,
    )
    registry.register_skill(new_skill)

    retriever = SkillRetriever(registry=registry, evidence_repo=repo)
    task = TaskSpec(
        key="task-gql",
        name="Implement GraphQL",
        task_type="graphql_api",
        required_capabilities=[AgentCapability.CODE_GENERATION],
        input_payload={"objective": "Build GraphQL schema and resolvers"},
    )

    matches = retriever.retrieve_skills_for_task(task=task, limit=1)
    assert len(matches) == 1
    assert matches[0].skill.skill_id == "brand-new-candidate"
    # Score is positive and bounded (discoverable)
    assert matches[0].total_score > 0.1


def test_outcome_grounded_adaptive_rag_utility_updates() -> None:
    tracker = SkillAdaptiveRAGTracker(max_positive_adjustment=0.4, max_negative_adjustment=0.4)

    # Record observation
    obs = tracker.record_observation(
        task_type="api_implementation",
        objective="Create REST endpoints",
        retrieved_skill_ids=["fastapi-crud-endpoint", "generic-api"],
        selected_skill_id="fastapi-crud-endpoint",
        agent_id="codex",
        execution_id="exec-101",
        task_id="task-1",
    )
    assert obs.selected_skill_id == "fastapi-crud-endpoint"

    # Prior to feedback, utility adjustment is 0.0
    adj_initial = tracker.get_utility_adjustment("fastapi-crud-endpoint", "api_implementation")
    assert adj_initial == 0.0

    # 1. Positive verified feedback -> utility adjustment increases (+0.4)
    tracker.record_feedback(
        task_type="api_implementation",
        objective="Create REST endpoints",
        skill_id="fastapi-crud-endpoint",
        verification_status=VerificationStatus.PASSED,
        agent_id="codex",
        execution_id="exec-101",
    )
    adj_pos = tracker.get_utility_adjustment("fastapi-crud-endpoint", "api_implementation")
    assert adj_pos > 0.0
    assert adj_pos <= 0.4

    # 2. Record failure on another skill -> utility adjustment decreases (-0.4)
    tracker.record_feedback(
        task_type="api_implementation",
        objective="Create REST endpoints",
        skill_id="bad-skill",
        verification_status=VerificationStatus.FAILED,
        agent_id="codex",
        execution_id="exec-102",
    )
    adj_neg = tracker.get_utility_adjustment("bad-skill", "api_implementation")
    assert adj_neg < 0.0
    assert adj_neg >= -0.4
