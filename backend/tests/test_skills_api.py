"""Deterministic integration tests for Skill Foundry REST API."""

from pathlib import Path

import pytest
from httpx import AsyncClient

from app.api.deps import (
    get_candidate_skill_foundry,
    get_skill_evidence_repo,
    get_skill_lifecycle_manager,
    get_skill_registry,
)
from app.contracts.skills import SkillCategory, SkillContract, SkillStatus
from app.core.config import get_settings
from app.engine.skills.evidence import InMemorySkillEvidenceRepository
from app.engine.skills.foundry import CandidateSkillFoundry
from app.engine.skills.lifecycle import SkillLifecycleManager
from app.engine.skills.registry import SkillRegistry
from app.engine.skills.vault import ObsidianSkillVault
from app.main import app


async def test_skills_api_crud_and_search(
    tmp_path: Path, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "skill_vault_root", str(tmp_path / "Vault"))

    # 1. Populate disposable vault
    vault = ObsidianSkillVault(vault_root=tmp_path / "Vault")
    skill1 = SkillContract(
        skill_id="fastapi-crud-endpoint",
        version="1.0.0",
        name="FastAPI CRUD Endpoint",
        description="Creates RESTful FastAPI CRUD endpoints",
        category=SkillCategory.BACKEND,
        task_types=("api_implementation", "backend"),
        languages=("python",),
        frameworks=("fastapi",),
        status=SkillStatus.VERIFIED,
    )
    vault.write_skill(skill1)

    evidence_repo = InMemorySkillEvidenceRepository()
    registry = SkillRegistry(evidence_repo=evidence_repo, vault=vault)
    foundry = CandidateSkillFoundry(registry=registry, evidence_repo=evidence_repo, vault=vault)
    lifecycle_mgr = SkillLifecycleManager(registry=registry, evidence_repo=evidence_repo)

    # Wire isolated test dependencies
    app.dependency_overrides[get_skill_registry] = lambda: registry
    app.dependency_overrides[get_skill_evidence_repo] = lambda: evidence_repo
    app.dependency_overrides[get_candidate_skill_foundry] = lambda: foundry
    app.dependency_overrides[get_skill_lifecycle_manager] = lambda: lifecycle_mgr

    try:
        # Ingest vault via API
        resp_ingest = await client.post(
            "/api/v1/skills/vault/ingest", json={"vault_path": str(tmp_path / "Vault")}
        )
        assert resp_ingest.status_code == 200
        assert resp_ingest.json()["ingested_count"] == 1

        # List skills
        resp_list = await client.get("/api/v1/skills")
        assert resp_list.status_code == 200
        items = resp_list.json()
        assert len(items) == 1
        assert items[0]["skill_id"] == "fastapi-crud-endpoint"

        # Get skill by ID
        resp_get = await client.get("/api/v1/skills/fastapi-crud-endpoint")
        assert resp_get.status_code == 200
        assert resp_get.json()["name"] == "FastAPI CRUD Endpoint"

        # Search skills
        resp_search = await client.post(
            "/api/v1/skills/search",
            json={
                "task_type": "api_implementation",
                "objective": "Build FastAPI endpoint",
                "languages": ["python"],
            },
        )
        assert resp_search.status_code == 200
        matches = resp_search.json()
        assert len(matches) == 1
        assert matches[0]["skill"]["skill_id"] == "fastapi-crud-endpoint"

        # Propose candidate and approve via API
        prop, _ = foundry.propose_candidate_skill(
            skill_id="candidate-skill",
            name="Candidate Skill",
            description="Candidate description",
            category=SkillCategory.TESTING,
            task_types=("testing",),
            capabilities=(),
            languages=(),
            frameworks=(),
            procedure="Test procedure",
            verification_contract={},
            origin_execution_ids=("exec-1", "exec-2"),
        )
        assert prop is not None

        # List candidates
        resp_cand = await client.get("/api/v1/skills/candidates")
        assert resp_cand.status_code == 200
        cands = resp_cand.json()
        assert len(cands) == 1
        assert cands[0]["proposal_id"] == prop.proposal_id

        # Approve candidate
        resp_approve = await client.post(f"/api/v1/skills/candidates/{prop.proposal_id}/approve")
        assert resp_approve.status_code == 200
        assert resp_approve.json()["skill_id"] == "candidate-skill"
        assert resp_approve.json()["status"] == "CANDIDATE"

        # Deprecate skill
        resp_dep = await client.post("/api/v1/skills/candidate-skill/deprecate")
        assert resp_dep.status_code == 200
        assert resp_dep.json()["status"] == "DEPRECATED"
    finally:
        app.dependency_overrides.pop(get_skill_registry, None)
        app.dependency_overrides.pop(get_skill_evidence_repo, None)
        app.dependency_overrides.pop(get_candidate_skill_foundry, None)
        app.dependency_overrides.pop(get_skill_lifecycle_manager, None)
