"""Deterministic unit tests for Obsidian Skill Vault, parsing, and boundary safety."""

from pathlib import Path

import pytest

from app.contracts.enums import AgentCapability
from app.contracts.skills import SkillCategory, SkillContract, SkillStatus
from app.engine.skills.errors import (
    MalformedSkillError,
    SkillVaultSecurityError,
)
from app.engine.skills.vault import (
    MAX_SKILL_FILE_SIZE_BYTES,
    ObsidianSkillVault,
    parse_skill_markdown,
    serialize_skill_to_markdown,
)


def test_parse_skill_markdown_full_structure() -> None:
    raw_md = """---
skill_id: pytest-api-tests
version: 1.2.0
status: VERIFIED
category: Testing
task_types:
  - testing
  - verification
capabilities:
  - code_generation
  - test_execution
languages:
  - python
frameworks:
  - pytest
  - httpx
preconditions:
  - pytest installed
  - test database accessible
contraindications:
  - Do not use for browser UI tests
---

# Pytest API Tests

## When to use
Use this skill to implement comprehensive async API integration tests.

## Preconditions
- Python virtual environment is active
- Backend server is reachable or mockable

## Contraindications and Common Failures
- Failing to isolate database state between test runs
- Hardcoded localhost ports

## Procedure
1. Create tests/test_api_endpoints.py
2. Use TestClient or AsyncClient
3. Verify status codes and response schemas

## Verification
- Run `pytest tests/test_api_endpoints.py -v`
- Assert all test cases pass with 100% assertions met
"""

    skill = parse_skill_markdown(raw_md, source_path="Skills/Testing/pytest-api-tests.md")
    assert skill.skill_id == "pytest-api-tests"
    assert skill.version == "1.2.0"
    assert skill.status == SkillStatus.VERIFIED
    assert skill.category == SkillCategory.TESTING
    assert "testing" in skill.task_types
    assert AgentCapability.CODE_GENERATION in skill.capabilities
    assert AgentCapability.TEST_EXECUTION in skill.capabilities
    assert "python" in skill.languages
    assert "pytest" in skill.frameworks
    assert len(skill.preconditions) >= 2
    assert len(skill.contraindications) >= 1
    assert "Create tests/test_api_endpoints.py" in skill.procedure
    assert skill.verification_contract["criteria"]


def test_serialize_and_roundtrip_skill() -> None:
    skill = SkillContract(
        skill_id="react-component",
        version="2.0.0",
        name="React Component",
        description="Creates modern TypeScript React functional components",
        category=SkillCategory.FRONTEND,
        task_types=("frontend", "ui_component"),
        capabilities=(AgentCapability.CODE_GENERATION, AgentCapability.FILE_EDITING),
        languages=("typescript", "javascript"),
        frameworks=("react", "tailwind"),
        preconditions=("Node.js and npm installed",),
        contraindications=("Do not use class components",),
        procedure="1. Create component file\n2. Define TypeScript props\n3. Export component",
        verification_contract={"criteria": ["Component renders without runtime errors"]},
        status=SkillStatus.TRUSTED,
    )

    md = serialize_skill_to_markdown(skill)
    assert "skill_id: react-component" in md
    assert "# React Component" in md
    assert "## When to use" in md

    # Roundtrip parse
    reparsed = parse_skill_markdown(md, source_path="react-component.md")
    assert reparsed.skill_id == skill.skill_id
    assert reparsed.version == skill.version
    assert reparsed.status == SkillStatus.TRUSTED
    assert reparsed.category == SkillCategory.FRONTEND
    assert "typescript" in reparsed.languages


def test_vault_scanner_and_directory_creation(tmp_path: Path) -> None:
    vault_dir = tmp_path / "Keystone-Skills-Test"
    vault = ObsidianSkillVault(vault_root=vault_dir)

    # Check directories were created
    assert (vault_dir / "Skills" / "Backend").exists()
    assert (vault_dir / "Skills" / "Frontend").exists()
    assert (vault_dir / "Candidates").exists()
    assert (vault_dir / "Deprecated").exists()

    # Write a test skill
    skill = SkillContract(
        skill_id="sql-optimization",
        version="1.0.0",
        name="SQL Query Optimization",
        description="Analyzes and indexes slow queries",
        category=SkillCategory.DATA_ENGINEERING,
        task_types=("database", "optimization"),
        capabilities=(AgentCapability.CODE_GENERATION,),
        languages=("sql",),
        frameworks=("postgresql",),
        procedure="1. Run EXPLAIN ANALYZE\n2. Add indexes\n3. Re-verify plan",
    )
    written_path = vault.write_skill(skill)
    assert written_path.exists()
    assert "DataEngineering" in str(written_path)

    # Scan skills
    skills, errors = vault.scan_skills()
    assert len(errors) == 0
    assert len(skills) == 1
    assert skills[0].skill_id == "sql-optimization"


def test_vault_path_traversal_protection(tmp_path: Path) -> None:
    vault_dir = tmp_path / "Vault"
    vault_dir.mkdir()

    # Outside file access attempt
    with pytest.raises(SkillVaultSecurityError, match="escapes vault root"):
        from app.engine.skills.vault import _safe_resolve_path

        _safe_resolve_path(vault_dir, "../outside.txt")


def test_oversized_file_rejected() -> None:
    huge_content = "a" * (MAX_SKILL_FILE_SIZE_BYTES + 100)
    with pytest.raises(MalformedSkillError, match="exceeds max size limit"):
        parse_skill_markdown(huge_content)


def test_bad_yaml_raises_malformed_error() -> None:
    bad_yaml_md = """---
skill_id: [unclosed list
version: 1.0.0
---

# Title
Body
"""
    with pytest.raises(MalformedSkillError, match="Malformed YAML frontmatter"):
        parse_skill_markdown(bad_yaml_md)
