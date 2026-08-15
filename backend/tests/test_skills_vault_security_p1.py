"""Deterministic security tests for Obsidian Vault root authorization and boundary containment."""

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.engine.skills.errors import SkillVaultSecurityError
from app.engine.skills.vault import (
    _safe_resolve_path,
)
from app.main import app


@pytest.mark.asyncio
async def test_api_rejects_arbitrary_unauthorized_vault_root(tmp_path: Path) -> None:
    # An unauthorized directory outside configured vault roots
    unauthorized_dir = tmp_path / "UnauthorizedVault"
    unauthorized_dir.mkdir()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/skills/vault/ingest",
            json={"vault_path": str(unauthorized_dir)},
        )
        assert response.status_code in (400, 403)
        assert (
            "not an authorized vault root" in response.text
            or "security violation" in response.text.lower()
        )


@pytest.mark.asyncio
async def test_api_accepts_configured_vault_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authorized_vault = tmp_path / "AuthorizedVault"
    authorized_vault.mkdir()
    (authorized_vault / "Skills" / "Backend").mkdir(parents=True)

    test_skill_md = """---
skill_id: auth-backend-skill
name: Authorized Backend Skill
version: 1.0.0
category: Backend
status: DRAFT
---
# Authorized Backend Skill
## When to use
Authorized test skill.
## Procedure
1. Step one
## Verification
- Test passes
"""
    skill_file = authorized_vault / "Skills" / "Backend" / "skill.md"
    skill_file.write_text(test_skill_md, encoding="utf-8")

    settings = get_settings()
    monkeypatch.setattr(settings, "skill_vault_root", str(authorized_vault))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Ingest without path (defaults to configured root)
        response1 = await client.post("/api/v1/skills/vault/ingest", json={})
        assert response1.status_code == 200
        data1 = response1.json()
        assert data1["ingested_count"] >= 1

        # 2. Ingest with explicit authorized path
        response2 = await client.post(
            "/api/v1/skills/vault/ingest",
            json={"vault_path": str(authorized_vault)},
        )
        assert response2.status_code == 200


def test_vault_path_traversal_and_symlink_escape(tmp_path: Path) -> None:
    vault_dir = tmp_path / "SecureVault"
    vault_dir.mkdir()
    outside_dir = tmp_path / "OutsideDir"
    outside_dir.mkdir()

    # Traversal attempt
    with pytest.raises(SkillVaultSecurityError, match="escapes vault root"):
        _safe_resolve_path(vault_dir, "../OutsideDir")

    # Symlink escape attempt (if symlinks supported on platform)
    symlink_path = vault_dir / "escaped_link"
    try:
        symlink_path.symlink_to(outside_dir, target_is_directory=True)
        with pytest.raises(SkillVaultSecurityError, match="escapes vault root"):
            _safe_resolve_path(vault_dir, "escaped_link/secret.txt")
    except (OSError, NotImplementedError):
        # Platform does not allow non-admin symlink creation
        pass
