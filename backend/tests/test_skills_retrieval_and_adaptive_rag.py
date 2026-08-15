"""Deterministic unit tests for SkillRetriever and Stage 7.5 Unified Adaptive RAG."""

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.contracts.enums import AgentCapability
from app.contracts.planning import TaskSpec
from app.contracts.skills import SkillCategory, SkillContract, SkillStatus
from app.contracts.verification import VerificationStatus
from app.database.base import Base
from app.engine.adaptive_retrieval.feedback import (
    InMemoryRetrievalFeedbackRepository,
    RetrievalFeedback,
)
from app.engine.adaptive_retrieval.models import RetrievalObservation
from app.engine.adaptive_retrieval.passport import RetrievalPassport
from app.engine.adaptive_retrieval.policy import AdaptiveRetrievalPolicy
from app.engine.learning.aggregation import MIN_SAMPLE_SIZE_FOR_CONFIDENCE
from app.engine.skills.adaptive_rag import (
    SkillAdaptiveRetrievalAdapter,
)
from app.engine.skills.evidence import (
    InMemorySkillEvidenceRepository,
    SkillExecutionEvidence,
    SqlAlchemySkillEvidenceRepository,
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


def test_skill_adaptive_retrieval_reuses_existing_engine() -> None:
    """Proves SkillAdaptiveRetrievalAdapter delegates 100% of its data models,

    passport generation, and scoring math to app.engine.adaptive_retrieval.
    """
    feedback_repo = InMemoryRetrievalFeedbackRepository()
    adapter = SkillAdaptiveRetrievalAdapter(feedback_repo=feedback_repo)

    # 1. Observation uses existing RetrievalObservation model
    obs = adapter.record_observation(
        task_type="api_implementation",
        objective="Create REST endpoints",
        retrieved_skill_ids=["fastapi-crud-endpoint", "generic-api"],
        selected_skill_id="fastapi-crud-endpoint",
        agent_id="codex",
        execution_id="exec-101",
        task_id="task-1",
    )
    assert isinstance(obs, RetrievalObservation)
    assert obs.task_type == "api_implementation"
    assert "fastapi-crud-endpoint" in obs.retrieved_chunk_ids
    assert obs.selected_chunk_ids == ("fastapi-crud-endpoint",)

    # 2. Feedback uses existing RetrievalFeedback model
    fb = adapter.record_feedback(
        task_type="api_implementation",
        objective="Create REST endpoints",
        skill_id="fastapi-crud-endpoint",
        verification_status=VerificationStatus.PASSED,
        agent_id="codex",
        execution_id="exec-101",
    )
    assert isinstance(fb, RetrievalFeedback)
    assert fb.chunk_ids == ("fastapi-crud-endpoint",)
    assert fb.is_verified_success is True

    # 3. Passport uses existing RetrievalPassport
    passport = adapter.get_passport_for_skill("fastapi-crud-endpoint")
    assert isinstance(passport, RetrievalPassport)
    assert passport.chunk_id == "fastapi-crud-endpoint"


def test_sample_gate_and_neutral_priors() -> None:
    """Proves:

    - n=0 -> neutral (0.0)
    - n=1 -> neutral (0.0, does not hit max bound)
    - n < MIN_SAMPLE_SIZE_FOR_CONFIDENCE (5) -> neutral (0.0)
    - n >= 5 -> bounded learned adjustment in [-0.15, +0.15]
    """
    adapter = SkillAdaptiveRetrievalAdapter()
    assert adapter.policy.minimum_verified_samples == MIN_SAMPLE_SIZE_FOR_CONFIDENCE
    assert MIN_SAMPLE_SIZE_FOR_CONFIDENCE == 5

    # n = 0: neutral
    adj_0 = adapter.get_utility_adjustment("fastapi-crud", "api_implementation")
    assert adj_0 == 0.0

    # n = 1: one verified success MUST remain neutral (0.0) and NOT jump to max bound
    adapter.record_feedback(
        task_type="api_implementation",
        objective="Create REST endpoints",
        skill_id="fastapi-crud",
        verification_status=VerificationStatus.PASSED,
        execution_id="exec-1",
    )
    adj_1 = adapter.get_utility_adjustment("fastapi-crud", "api_implementation")
    assert adj_1 == 0.0

    # n = 4 (< 5): still below confidence gate -> 0.0
    for i in range(2, 5):
        adapter.record_feedback(
            task_type="api_implementation",
            objective="Create REST endpoints",
            skill_id="fastapi-crud",
            verification_status=VerificationStatus.PASSED,
            execution_id=f"exec-{i}",
        )
    adj_4 = adapter.get_utility_adjustment("fastapi-crud", "api_implementation")
    assert adj_4 == 0.0

    # n = 5 (>= 5): clears confidence gate -> bounded positive adjustment (+0.15)
    adapter.record_feedback(
        task_type="api_implementation",
        objective="Create REST endpoints",
        skill_id="fastapi-crud",
        verification_status=VerificationStatus.PASSED,
        execution_id="exec-5",
    )
    adj_5 = adapter.get_utility_adjustment("fastapi-crud", "api_implementation")
    assert adj_5 == 0.15

    # Negative side: 5 consecutive failures produce -0.15
    for i in range(1, 6):
        adapter.record_feedback(
            task_type="api_implementation",
            objective="Create REST endpoints",
            skill_id="failing-skill",
            verification_status=VerificationStatus.FAILED,
            execution_id=f"exec-fail-{i}",
        )
    adj_fail_5 = adapter.get_utility_adjustment("failing-skill", "api_implementation")
    assert adj_fail_5 == -0.15


def test_sufficient_samples_change_future_retriever_ranking() -> None:
    """Proves that verified outcomes adjust future SkillRetriever ranking

    when sufficient samples exist, while preserving base relevance safeguards.
    """
    registry = SkillRegistry()
    evidence_repo = InMemorySkillEvidenceRepository()
    adaptive_adapter = SkillAdaptiveRetrievalAdapter(
        policy=AdaptiveRetrievalPolicy(
            enabled=True,
            minimum_verified_samples=5,
            max_positive_adjustment=0.15,
            max_negative_adjustment=0.15,
        )
    )

    # Two identical skills for the same task
    skill_a = SkillContract(
        skill_id="skill-backend-a",
        version="1.0.0",
        name="FastAPI Backend Builder A",
        description="Standard FastAPI REST service implementation",
        category=SkillCategory.BACKEND,
        task_types=("api_implementation",),
        capabilities=(AgentCapability.CODE_GENERATION,),
        languages=("python",),
        frameworks=("fastapi",),
        status=SkillStatus.VERIFIED,
    )
    skill_b = SkillContract(
        skill_id="skill-backend-b",
        version="1.0.0",
        name="FastAPI Backend Builder B",
        description="Standard FastAPI REST service implementation",
        category=SkillCategory.BACKEND,
        task_types=("api_implementation",),
        capabilities=(AgentCapability.CODE_GENERATION,),
        languages=("python",),
        frameworks=("fastapi",),
        status=SkillStatus.VERIFIED,
    )
    registry.register_skill(skill_a)
    registry.register_skill(skill_b)

    retriever = SkillRetriever(
        registry=registry,
        evidence_repo=evidence_repo,
        adaptive_tracker=adaptive_adapter,
    )
    task = TaskSpec(
        key="task-api",
        name="Build API",
        task_type="api_implementation",
        required_capabilities=[AgentCapability.CODE_GENERATION],
        input_payload={"objective": "Implement FastAPI user endpoints"},
    )

    # Initial ranking: both have 0 evidence, utility = 0.5 neutral
    initial_matches = retriever.retrieve_skills_for_task(task=task, limit=2)
    assert len(initial_matches) == 2
    assert initial_matches[0].verified_utility == 0.5
    assert initial_matches[1].verified_utility == 0.5

    # Feed 5 verified successes for Skill A
    for i in range(5):
        adaptive_adapter.record_feedback(
            task_type="api_implementation",
            objective="Implement FastAPI user endpoints",
            skill_id="skill-backend-a",
            verification_status=VerificationStatus.PASSED,
            execution_id=f"exec-a-{i}",
        )

    # Feed 5 verified failures for Skill B
    for i in range(5):
        adaptive_adapter.record_feedback(
            task_type="api_implementation",
            objective="Implement FastAPI user endpoints",
            skill_id="skill-backend-b",
            verification_status=VerificationStatus.FAILED,
            execution_id=f"exec-b-{i}",
        )

    # Re-retrieve: Skill A must have higher utility and rank #1
    updated_matches = retriever.retrieve_skills_for_task(task=task, limit=2)
    assert len(updated_matches) == 2
    assert updated_matches[0].skill.skill_id == "skill-backend-a"
    assert updated_matches[1].skill.skill_id == "skill-backend-b"
    assert updated_matches[0].verified_utility > updated_matches[1].verified_utility
    assert updated_matches[0].total_score > updated_matches[1].total_score


def test_objective_verification_only_updates_learning() -> None:
    """Proves only objective verification statuses feed learning:

    - PASSED is positive
    - FAILED is negative
    - INCONCLUSIVE / REQUIRES_HUMAN_REVIEW do NOT count as success
    """
    adapter = SkillAdaptiveRetrievalAdapter(
        policy=AdaptiveRetrievalPolicy(enabled=True, minimum_verified_samples=3)
    )

    # 3 INCONCLUSIVE runs
    for i in range(3):
        adapter.record_feedback(
            task_type="backend",
            skill_id="inconclusive-skill",
            verification_status=VerificationStatus.INCONCLUSIVE,
            execution_id=f"exec-inc-{i}",
        )
    # Success count is 0, success rate is 0.0 -> negative adjustment, never positive
    adj_inc = adapter.get_utility_adjustment("inconclusive-skill", "backend")
    assert adj_inc == -0.15


def test_restart_preserves_learned_skill_retrieval_signal(tmp_path: Path) -> None:
    """Proves restart reconstruction: previous verified skill retrieval outcomes

    stored in SQLite DB rehydrate the adapter and influence future ranking.
    """
    db_file = tmp_path / "restart_adaptive.db"
    db_url = f"sqlite:///{db_file}"
    engine = create_engine(db_url)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    evidence_repo = SqlAlchemySkillEvidenceRepository(session_factory=Session)

    # Record 5 verified executions in SQLite DB
    for i in range(5):
        evidence_repo.record_evidence(
            SkillExecutionEvidence(
                skill_id="persisted-fastapi-skill",
                skill_version="1.0.0",
                task_type="api_implementation",
                agent_id="codex",
                execution_id=f"exec-db-{i}",
                task_id=f"task-{i}",
                verification_status=VerificationStatus.PASSED,
                success=True,
                timestamp=datetime.now(UTC),
            )
        )

    # Recreate fresh adapter connected to the same DB session factory
    restarted_repo = SqlAlchemySkillEvidenceRepository(session_factory=Session)
    restarted_adapter = SkillAdaptiveRetrievalAdapter(
        evidence_repo=restarted_repo,
        policy=AdaptiveRetrievalPolicy(enabled=True, minimum_verified_samples=5),
    )

    # After restart, learned utility is +0.15 from the 5 persisted passes
    adj = restarted_adapter.get_utility_adjustment(
        "persisted-fastapi-skill", "api_implementation"
    )
    assert adj == 0.15


def test_zero_skill_path_still_works() -> None:
    """Proves empty registry returns empty match list safely."""
    registry = SkillRegistry()
    retriever = SkillRetriever(registry=registry)
    task = TaskSpec(
        key="task-empty",
        name="Empty task",
        task_type="unknown",
        required_capabilities=[AgentCapability.CODE_GENERATION],
    )
    matches = retriever.retrieve_skills_for_task(task=task)
    assert matches == []

