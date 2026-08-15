"""Deterministic unit tests for SkillRegistry, immutable versioning, and queries."""

from pathlib import Path

import pytest

from app.contracts.enums import AgentCapability
from app.contracts.skills import SkillCategory, SkillContract, SkillStatus
from app.engine.skills.errors import (
    SkillNotFoundError,
    SkillVersionConflictError,
)
from app.engine.skills.registry import SkillRegistry
from app.engine.skills.vault import ObsidianSkillVault


def test_registry_versioning_and_immutability() -> None:
    registry = SkillRegistry()

    v1 = SkillContract(
        skill_id="airflow-dag",
        version="1.0.0",
        name="Airflow DAG Creation",
        description="Creates production Airflow DAGs",
        category=SkillCategory.DATA_ENGINEERING,
        status=SkillStatus.VERIFIED,
        procedure="Create DAG definition",
    )
    registry.register_skill(v1)

    # Attempting to overwrite verified v1 must raise SkillVersionConflictError
    v1_mod = SkillContract(
        skill_id="airflow-dag",
        version="1.0.0",
        name="Modified Airflow DAG",
        description="Overwriting verified skill",
        category=SkillCategory.DATA_ENGINEERING,
        status=SkillStatus.DRAFT,
        procedure="Different procedure",
    )
    with pytest.raises(SkillVersionConflictError, match="Cannot overwrite immutable"):
        registry.register_skill(v1_mod)

    # Registering a new version 1.1.0 succeeds
    v1_1 = SkillContract(
        skill_id="airflow-dag",
        version="1.1.0",
        name="Airflow DAG Creation",
        description="Updated DAG with retries",
        category=SkillCategory.DATA_ENGINEERING,
        status=SkillStatus.CANDIDATE,
        procedure="Updated procedure with task retries",
    )
    registry.register_skill(v1_1)

    # Registering version 2.0.0 succeeds
    v2_0 = SkillContract(
        skill_id="airflow-dag",
        version="2.0.0",
        name="Airflow Taskflow DAG",
        description="Uses @task decorators",
        category=SkillCategory.DATA_ENGINEERING,
        status=SkillStatus.DRAFT,
        procedure="Taskflow API procedure",
    )
    registry.register_skill(v2_0)

    # Latest version lookup defaults to 2.0.0
    latest = registry.get_skill("airflow-dag")
    assert latest.version == "2.0.0"

    # Specific version lookup returns exact requested version
    old_v1 = registry.get_skill("airflow-dag", version="1.0.0")
    assert old_v1.version == "1.0.0"
    assert old_v1.status == SkillStatus.VERIFIED

    # All versions returned in sorted order
    all_v = registry.get_all_versions("airflow-dag")
    assert [s.version for s in all_v] == ["1.0.0", "1.1.0", "2.0.0"]


def test_registry_filters_and_queries() -> None:
    registry = SkillRegistry()

    s1 = SkillContract(
        skill_id="python-api",
        version="1.0.0",
        name="Python API",
        description="FastAPI REST API",
        category=SkillCategory.BACKEND,
        task_types=("api_implementation",),
        capabilities=(AgentCapability.CODE_GENERATION,),
        languages=("python",),
        frameworks=("fastapi",),
        status=SkillStatus.VERIFIED,
    )
    s2 = SkillContract(
        skill_id="react-ui",
        version="1.0.0",
        name="React UI",
        description="React component creation",
        category=SkillCategory.FRONTEND,
        task_types=("frontend_ui",),
        capabilities=(AgentCapability.CODE_GENERATION, AgentCapability.FILE_EDITING),
        languages=("typescript",),
        frameworks=("react",),
        status=SkillStatus.TRUSTED,
    )
    s3 = SkillContract(
        skill_id="pytest-suite",
        version="1.0.0",
        name="Pytest Suite",
        description="Pytest unit tests",
        category=SkillCategory.TESTING,
        task_types=("testing",),
        capabilities=(AgentCapability.TEST_EXECUTION,),
        languages=("python",),
        frameworks=("pytest",),
        status=SkillStatus.CANDIDATE,
    )
    registry.register_skill(s1)
    registry.register_skill(s2)
    registry.register_skill(s3)

    # Filter by category
    backend_skills = registry.list_skills(category=SkillCategory.BACKEND)
    assert len(backend_skills) == 1
    assert backend_skills[0].skill_id == "python-api"

    # Filter by language
    py_skills = registry.list_skills(language="python")
    assert len(py_skills) == 2
    assert {s.skill_id for s in py_skills} == {"python-api", "pytest-suite"}

    # Filter by capability
    test_exec_skills = registry.list_skills(capability=AgentCapability.TEST_EXECUTION)
    assert len(test_exec_skills) == 1
    assert test_exec_skills[0].skill_id == "pytest-suite"

    # Filter by status
    trusted_skills = registry.list_skills(status=SkillStatus.TRUSTED)
    assert len(trusted_skills) == 1
    assert trusted_skills[0].skill_id == "react-ui"


def test_registry_vault_ingestion(tmp_path: Path) -> None:
    vault = ObsidianSkillVault(vault_root=tmp_path / "Vault")

    skill = SkillContract(
        skill_id="devops-dockerfile",
        version="1.0.0",
        name="Dockerfile Creation",
        description="Creates multi-stage Dockerfiles",
        category=SkillCategory.DEVOPS,
        task_types=("devops", "containerization"),
        capabilities=(AgentCapability.CODE_GENERATION,),
        procedure="1. Base image\n2. Build stage\n3. Runtime stage",
        status=SkillStatus.VERIFIED,
    )
    vault.write_skill(skill)

    registry = SkillRegistry(vault=vault)
    count, errors = registry.ingest_vault()
    assert count == 1
    assert len(errors) == 0

    ingested = registry.get_skill("devops-dockerfile")
    assert ingested.name == "Dockerfile Creation"
    assert ingested.status == SkillStatus.VERIFIED


def test_registry_not_found_raises() -> None:
    registry = SkillRegistry()
    with pytest.raises(SkillNotFoundError):
        registry.get_skill("non-existent-skill")
