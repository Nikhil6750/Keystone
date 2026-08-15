"""Deterministic tests for DB persistence, restart reconstruction, idempotency,
and immutable version preservation.
"""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.contracts.enums import AgentCapability
from app.contracts.skills import SkillCategory, SkillContract, SkillStatus
from app.contracts.verification import VerificationStatus
from app.database.base import Base
from app.engine.skills.errors import SkillVersionConflictError
from app.engine.skills.evidence import (
    SkillExecutionEvidence,
    SqlAlchemySkillEvidenceRepository,
)
from app.engine.skills.registry import SkillRegistry


def test_db_persistence_and_restart_reconstruction(tmp_path: Path) -> None:
    db_file = tmp_path / "test_keystone_skills.db"
    db_url = f"sqlite:///{db_file}"
    engine = create_engine(db_url)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    # 1. Start Session 1: Register skills and record evidence
    evidence_repo1 = SqlAlchemySkillEvidenceRepository(session_factory=Session)
    registry1 = SkillRegistry(evidence_repo=evidence_repo1, session_factory=Session)

    skill_v1 = SkillContract(
        skill_id="fastapi-rest-service",
        version="1.0.0",
        name="FastAPI REST Service",
        description="Standard pattern for creating robust FastAPI endpoints",
        category=SkillCategory.BACKEND,
        task_types=("api_implementation", "backend"),
        capabilities=(AgentCapability.CODE_GENERATION,),
        languages=("python",),
        frameworks=("fastapi",),
        preconditions=("Python 3.11+",),
        contraindications=("Do not use global state",),
        procedure="1. Declare schemas\n2. Define routers\n3. Implement logic",
        verification_contract={"criteria": ["Endpoints return 200/201"]},
        status=SkillStatus.VERIFIED,
    )
    registry1.register_skill(skill_v1)

    # Record 3 verified evidence items
    for i in range(3):
        evidence_repo1.record_evidence(
            SkillExecutionEvidence(
                skill_id="fastapi-rest-service",
                skill_version="1.0.0",
                task_type="api_implementation",
                agent_id="agent-python-expert",
                execution_id=f"exec-persisted-{i}",
                task_id=f"task-persist-{i}",
                verification_status=VerificationStatus.PASSED,
                success=True,
                latency_ms=120.0 + i * 10,
            )
        )

    # 2. Simulate complete process restart (brand new repository instances reading DB)
    evidence_repo2 = SqlAlchemySkillEvidenceRepository(session_factory=Session)
    registry2 = SkillRegistry(evidence_repo=evidence_repo2, session_factory=Session)

    # Verify skill survived restart
    loaded_skill = registry2.get_skill("fastapi-rest-service", "1.0.0")
    assert loaded_skill.skill_id == "fastapi-rest-service"
    assert loaded_skill.version == "1.0.0"
    assert loaded_skill.status == SkillStatus.VERIFIED

    # Verify evidence survived restart
    loaded_evidence = evidence_repo2.get_evidence_for_skill("fastapi-rest-service", "1.0.0")
    assert len(loaded_evidence) == 3
    metrics = evidence_repo2.get_metrics_for_skill("fastapi-rest-service", "1.0.0")
    assert metrics.total_samples == 3
    assert metrics.verified_successes == 3
    assert metrics.smoothed_reliability() == (3 + 1.0) / (3 + 2.0)  # 4/5 = 0.80


def test_evidence_idempotency_prevents_duplicate_counting(tmp_path: Path) -> None:
    db_file = tmp_path / "test_idempotency.db"
    db_url = f"sqlite:///{db_file}"
    engine = create_engine(db_url)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    repo = SqlAlchemySkillEvidenceRepository(session_factory=Session)

    evidence = SkillExecutionEvidence(
        skill_id="pytest-generator",
        skill_version="1.0.0",
        task_type="testing",
        agent_id="agent-tester",
        execution_id="exec-100",
        task_id="task-200",
        verification_status=VerificationStatus.PASSED,
        success=True,
        latency_ms=150.0,
    )

    # Record the exact same execution evidence 5 times
    for _ in range(5):
        repo.record_evidence(evidence)

    # Must contain exactly 1 record, not 5
    records = repo.get_evidence_for_skill("pytest-generator", "1.0.0")
    assert len(records) == 1
    metrics = repo.get_metrics_for_skill("pytest-generator", "1.0.0")
    assert metrics.total_samples == 1
    assert metrics.verified_successes == 1


def test_verified_and_trusted_immutability_rejection(tmp_path: Path) -> None:
    db_file = tmp_path / "test_immutability.db"
    db_url = f"sqlite:///{db_file}"
    engine = create_engine(db_url)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    registry = SkillRegistry(session_factory=Session)

    verified_skill = SkillContract(
        skill_id="db-migration",
        version="1.0.0",
        name="Alembic DB Migration",
        description="Runs alembic revisions",
        category=SkillCategory.DEVOPS,
        task_types=("migration",),
        capabilities=(AgentCapability.CODE_GENERATION,),
        procedure="1. Check revisions\n2. Run upgrade head",
        verification_contract={"criteria": ["Migration exits 0"]},
        status=SkillStatus.VERIFIED,
    )
    registry.register_skill(verified_skill)

    # 1. Attempting to register identical content is idempotent (allowed)
    same_registered = registry.register_skill(verified_skill, allow_overwrite_draft=True)
    assert same_registered.version == "1.0.0"

    # 2. Overwriting VERIFIED skill with modified content MUST fail
    # even if allow_overwrite_draft=True
    modified_skill = SkillContract(
        skill_id="db-migration",
        version="1.0.0",
        name="Modified DB Migration",
        description="Modified procedure",
        category=SkillCategory.DEVOPS,
        task_types=("migration",),
        capabilities=(AgentCapability.CODE_GENERATION,),
        procedure="1. Modified procedure that would corrupt locked skill",
        verification_contract={"criteria": ["Different criteria"]},
        status=SkillStatus.DRAFT,
    )

    try:
        registry.register_skill(modified_skill, allow_overwrite_draft=True)
        raise AssertionError("Expected SkillVersionConflictError when overwriting VERIFIED skill")
    except SkillVersionConflictError as exc:
        assert "Cannot overwrite immutable VERIFIED skill" in str(exc)

    # 3. New version registration is preserved without conflict
    skill_v2 = SkillContract(
        skill_id="db-migration",
        version="1.1.0",
        name="Alembic DB Migration V2",
        description="Upgraded migration skill",
        category=SkillCategory.DEVOPS,
        task_types=("migration",),
        capabilities=(AgentCapability.CODE_GENERATION,),
        procedure="1. Upgrade with rollback guard",
        verification_contract={"criteria": ["Rollback guard active"]},
        status=SkillStatus.DRAFT,
    )
    registry.register_skill(skill_v2)

    # Both versions must exist in history
    versions = registry.get_all_versions("db-migration")
    assert len(versions) == 2
    assert [v.version for v in versions] == ["1.0.0", "1.1.0"]
