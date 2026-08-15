"""Stage 9C Machine-Readable Skill Registry.

Responsibilities:
- Ingest Markdown skills from vault or memory.
- Validate metadata and neutral contracts.
- Manage versions (e.g. 1.0.0, 1.1.0, 2.0.0).
- Query and filter by task_type, capabilities, languages, frameworks, status, category.
- Update lifecycle states.
- Link to evidence repositories.
"""

import contextlib
from datetime import UTC, datetime

from app.contracts.enums import AgentCapability
from app.contracts.skills import SkillCategory, SkillContract, SkillStatus
from app.engine.skills.errors import (
    SkillNotFoundError,
    SkillValidationError,
    SkillVersionConflictError,
)
from app.engine.skills.evidence import SkillEvidenceRepository
from app.engine.skills.vault import ObsidianSkillVault


def _parse_version_tuple(v: str) -> tuple[int, ...]:
    """Parse semver-like version string into integer tuple for sorting."""
    parts = []
    for chunk in v.strip().split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    return tuple(parts) if parts else (0, 0, 0)


class SkillRegistry:
    """Central in-memory machine-readable registry of verified skills and versions."""

    def __init__(
        self,
        evidence_repo: SkillEvidenceRepository | None = None,
        vault: ObsidianSkillVault | None = None,
    ) -> None:
        self._skills_by_id_and_version: dict[tuple[str, str], SkillContract] = {}
        self._latest_version_by_id: dict[str, str] = {}
        self._evidence_repo = evidence_repo
        self._vault = vault

    def register_skill(
        self, skill: SkillContract, allow_overwrite_draft: bool = False
    ) -> SkillContract:
        """Register a new skill or a new version of an existing skill.

        Invariant: NEVER silently overwrite a VERIFIED or TRUSTED skill version.
        """
        key = (skill.skill_id, skill.version)
        existing = self._skills_by_id_and_version.get(key)

        if existing is not None:
            is_locked = existing.status in (SkillStatus.VERIFIED, SkillStatus.TRUSTED)
            if is_locked and not allow_overwrite_draft:
                raise SkillVersionConflictError(
                    f"Cannot overwrite immutable {existing.status.value} skill '{skill.skill_id}' "
                    f"v{skill.version}. Please bump version (e.g. 1.0.1 or 1.1.0)."
                )
            if existing.status == SkillStatus.DRAFT and allow_overwrite_draft:
                # Allowed draft update
                pass
            elif existing == skill:
                # Idempotent registration
                return existing
            elif not allow_overwrite_draft:
                raise SkillVersionConflictError(
                    f"Skill '{skill.skill_id}' v{skill.version} is already registered."
                )

        self._skills_by_id_and_version[key] = skill

        # Update latest version pointer
        current_latest = self._latest_version_by_id.get(skill.skill_id)
        if current_latest is None:
            self._latest_version_by_id[skill.skill_id] = skill.version
        else:
            if _parse_version_tuple(skill.version) >= _parse_version_tuple(current_latest):
                self._latest_version_by_id[skill.skill_id] = skill.version

        return skill

    def get_skill(self, skill_id: str, version: str | None = None) -> SkillContract:
        """Get a skill by ID and optional version. Defaults to latest version."""
        if version is not None:
            key = (skill_id, version)
            skill = self._skills_by_id_and_version.get(key)
            if skill is None:
                raise SkillNotFoundError(f"Skill '{skill_id}' v{version} not found in registry")
            return skill

        latest_v = self._latest_version_by_id.get(skill_id)
        if latest_v is None:
            raise SkillNotFoundError(f"Skill '{skill_id}' not found in registry")
        return self._skills_by_id_and_version[(skill_id, latest_v)]

    def get_all_versions(self, skill_id: str) -> list[SkillContract]:
        """Return all historical versions of a skill, sorted by version ascending."""
        versions = [
            skill
            for (sid, v), skill in self._skills_by_id_and_version.items()
            if sid == skill_id
        ]
        versions.sort(key=lambda s: _parse_version_tuple(s.version))
        return versions

    def list_skills(
        self,
        status: SkillStatus | None = None,
        category: SkillCategory | str | None = None,
        task_type: str | None = None,
        capability: AgentCapability | None = None,
        language: str | None = None,
        framework: str | None = None,
        latest_only: bool = True,
    ) -> list[SkillContract]:
        """Query skills matching given filters."""
        if latest_only:
            candidates = [
                self._skills_by_id_and_version[(sid, latest_v)]
                for sid, latest_v in self._latest_version_by_id.items()
            ]
        else:
            candidates = list(self._skills_by_id_and_version.values())

        results = []
        for s in candidates:
            if status is not None and s.status != status:
                continue
            if category is not None:
                cat_val = category.value if isinstance(category, SkillCategory) else category
                if isinstance(s.category, SkillCategory):
                    s_cat_val = s.category.value
                else:
                    s_cat_val = s.category
                if cat_val.lower() != s_cat_val.lower():
                    continue
            if task_type is not None and task_type not in s.task_types:
                continue
            if capability is not None and capability not in s.capabilities:
                continue
            if language is not None:
                skill_langs = [item.lower() for item in s.languages]
                if language.lower() not in skill_langs:
                    continue
            if framework is not None:
                skill_fws = [item.lower() for item in s.frameworks]
                if framework.lower() not in skill_fws:
                    continue
            results.append(s)

        # Deterministic sorting by skill_id, version
        results.sort(key=lambda s: (s.skill_id, _parse_version_tuple(s.version)))
        return results

    def update_skill_status(
        self, skill_id: str, new_status: SkillStatus, version: str | None = None
    ) -> SkillContract:
        """Update lifecycle status of a skill in the registry."""
        current = self.get_skill(skill_id, version)
        updated = SkillContract(
            skill_id=current.skill_id,
            version=current.version,
            name=current.name,
            description=current.description,
            category=current.category,
            task_types=current.task_types,
            capabilities=current.capabilities,
            languages=current.languages,
            frameworks=current.frameworks,
            preconditions=current.preconditions,
            contraindications=current.contraindications,
            procedure=current.procedure,
            verification_contract=current.verification_contract,
            source=current.source,
            provenance=current.provenance,
            status=new_status,
            created_at=current.created_at,
            updated_at=datetime.now(UTC),
        )
        self._skills_by_id_and_version[(updated.skill_id, updated.version)] = updated

        # If vault is configured, optionally sync status to vault
        if self._vault is not None:
            with contextlib.suppress(Exception):
                self._vault.write_skill(updated)

        return updated

    def ingest_vault(
        self, vault: ObsidianSkillVault | None = None
    ) -> tuple[int, list[tuple[str, str]]]:
        """Ingest all skills from an Obsidian vault. Returns (ingested_count, errors)."""
        target_vault = vault or self._vault
        if target_vault is None:
            raise SkillValidationError("No ObsidianSkillVault configured for ingestion")

        skills, errors = target_vault.scan_skills()
        ingested = 0
        for skill in skills:
            try:
                self.register_skill(skill, allow_overwrite_draft=True)
                ingested += 1
            except Exception as e:
                errors.append((skill.skill_id, str(e)))

        return ingested, errors


__all__ = ["SkillRegistry"]
