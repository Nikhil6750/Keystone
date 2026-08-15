"""Deterministic unit tests for SkillContract, neutral priors, and validation."""

import pytest

from app.contracts.enums import AgentCapability
from app.contracts.skills import (
    SkillCategory,
    SkillContract,
    SkillContractValidationError,
    SkillStatus,
)


def test_skill_contract_valid_creation() -> None:
    skill = SkillContract(
        skill_id="fastapi-crud-endpoint",
        version="1.0.0",
        name="FastAPI CRUD Endpoint",
        description="Implements RESTful CRUD endpoints in FastAPI",
        category=SkillCategory.BACKEND,
        task_types=("api_implementation", "crud"),
        capabilities=(AgentCapability.CODE_GENERATION, AgentCapability.FILE_EDITING),
        languages=("python",),
        frameworks=("fastapi", "pydantic"),
        preconditions=("Python 3.10+ installed",),
        contraindications=("Do not use for GraphQL APIs",),
        procedure="1. Define Pydantic schema\n2. Create router\n3. Implement endpoints",
        verification_contract={
            "criteria": ["Endpoints return 200/201", "Schema validation passes"]
        },
    )
    assert skill.skill_id == "fastapi-crud-endpoint"
    assert skill.version == "1.0.0"
    assert skill.category == SkillCategory.BACKEND
    assert skill.status == SkillStatus.DRAFT
    assert skill.is_eligible_for_retrieval() is True


def test_skill_contract_rejects_blank_fields() -> None:
    with pytest.raises(SkillContractValidationError, match="skill_id must not be blank"):
        SkillContract(
            skill_id="   ",
            version="1.0.0",
            name="Test",
            description="desc",
            category=SkillCategory.GENERAL,
        )

    with pytest.raises(SkillContractValidationError, match="version must not be blank"):
        SkillContract(
            skill_id="test",
            version="",
            name="Test",
            description="desc",
            category=SkillCategory.GENERAL,
        )

    with pytest.raises(SkillContractValidationError, match="name must not be blank"):
        SkillContract(
            skill_id="test",
            version="1.0.0",
            name=" ",
            description="desc",
            category=SkillCategory.GENERAL,
        )


def test_skill_contract_forbids_provider_specific_fields() -> None:
    with pytest.raises(SkillContractValidationError, match="Provider-specific field"):
        SkillContract(
            skill_id="test-skill",
            version="1.0.0",
            name="Test Skill",
            description="desc",
            category=SkillCategory.BACKEND,
            provenance={"preferred_codex": True},
        )

    with pytest.raises(SkillContractValidationError, match="Provider-specific field"):
        SkillContract(
            skill_id="test-skill",
            version="1.0.0",
            name="Test Skill",
            description="desc",
            category=SkillCategory.BACKEND,
            provenance={"preferred_claude": 0.95},
        )

    with pytest.raises(SkillContractValidationError, match="Provider-specific field"):
        SkillContract(
            skill_id="test-skill",
            version="1.0.0",
            name="Test Skill",
            description="desc",
            category=SkillCategory.BACKEND,
            provenance={"preferred_antigravity": True},
        )


def test_deprecated_skill_not_eligible_for_retrieval() -> None:
    skill = SkillContract(
        skill_id="legacy-endpoint",
        version="1.0.0",
        name="Legacy Endpoint",
        description="Deprecated approach",
        category=SkillCategory.BACKEND,
        status=SkillStatus.DEPRECATED,
    )
    assert skill.is_eligible_for_retrieval() is False
