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
from typing import Any

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
    """Central registry of verified skills and versions with durable persistence."""

    def __init__(
        self,
        evidence_repo: SkillEvidenceRepository | None = None,
        vault: ObsidianSkillVault | None = None,
        session_factory: Any = None,
    ) -> None:
        self._skills_by_id_and_version: dict[tuple[str, str], SkillContract] = {}
        self._latest_version_by_id: dict[str, str] = {}
        self._evidence_repo = evidence_repo
        self._vault = vault
        self._session_factory = session_factory

        # Reconstruct from DB if session factory is provided
        if self._session_factory is not None:
            self.reload_from_db()

    def _get_session(self) -> Any:
        if self._session_factory is None:
            return None
        if callable(self._session_factory):
            return self._session_factory()
        return self._session_factory

    def reload_from_db(self) -> int:
        """Reconstruct registry in-memory state from database records."""
        session = self._get_session()
        if session is None:
            return 0

        from app.models.skills import SkillRecord

        try:
            records = session.query(SkillRecord).all()
            count = 0
            for rec in records:
                skill = rec.to_contract()
                key = (skill.skill_id, skill.version)
                self._skills_by_id_and_version[key] = skill
                current_latest = self._latest_version_by_id.get(skill.skill_id)
                if current_latest is None or _parse_version_tuple(
                    skill.version
                ) >= _parse_version_tuple(current_latest):
                    self._latest_version_by_id[skill.skill_id] = skill.version
                count += 1
            return count
        except Exception:
            return 0
        finally:
            if callable(self._session_factory) and session is not None:
                session.close()

    def register_skill(
        self, skill: SkillContract, allow_overwrite_draft: bool = False
    ) -> SkillContract:
        """Register a new skill or a new version of an existing skill.

        Invariant: NEVER silently overwrite a VERIFIED or TRUSTED skill version,
        even if allow_overwrite_draft is True.
        """
        key = (skill.skill_id, skill.version)
        existing = self._skills_by_id_and_version.get(key)

        if existing is not None:
            is_locked = existing.status in (SkillStatus.VERIFIED, SkillStatus.TRUSTED)
            if is_locked:
                if existing == skill:
                    # Idempotent registration of identical content
                    return existing
                raise SkillVersionConflictError(
                    f"Cannot overwrite immutable {existing.status.value} skill '{skill.skill_id}' "
                    f"v{skill.version}. Please bump version (e.g. 1.0.1 or 1.1.0)."
                )
            if existing.status == SkillStatus.DRAFT:
                if allow_overwrite_draft or existing == skill:
                    # Allowed draft update
                    pass
                else:
                    raise SkillVersionConflictError(
                        f"Draft skill '{skill.skill_id}' v{skill.version} is already registered."
                    )
            elif existing == skill:
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

        # Persist to DB if database session factory exists
        session = self._get_session()
        if session is not None:
            from app.models.skills import SkillRecord

            try:
                db_record = (
                    session.query(SkillRecord)
                    .filter_by(skill_id=skill.skill_id, version=skill.version)
                    .first()
                )
                if db_record is not None:
                    db_record.name = skill.name
                    db_record.description = skill.description
                    db_record.category = (
                        skill.category.value
                        if isinstance(skill.category, SkillCategory)
                        else str(skill.category)
                    )
                    db_record.status = skill.status.value
                    db_record.task_types = list(skill.task_types)
                    db_record.capabilities = [c.value for c in skill.capabilities]
                    db_record.languages = list(skill.languages)
                    db_record.frameworks = list(skill.frameworks)
                    db_record.preconditions = list(skill.preconditions)
                    db_record.contraindications = list(skill.contraindications)
                    db_record.procedure = skill.procedure
                    db_record.verification_contract = dict(skill.verification_contract)
                    db_record.source = skill.source
                    db_record.provenance = dict(skill.provenance)
                    db_record.updated_at = skill.updated_at
                else:
                    new_rec = SkillRecord.from_contract(skill)
                    session.add(new_rec)
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                if callable(self._session_factory):
                    session.close()

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
            skill for (sid, v), skill in self._skills_by_id_and_version.items() if sid == skill_id
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

        # Persist status to DB
        session = self._get_session()
        if session is not None:
            from app.models.skills import SkillRecord

            try:
                rec = (
                    session.query(SkillRecord)
                    .filter_by(skill_id=updated.skill_id, version=updated.version)
                    .first()
                )
                if rec is not None:
                    rec.status = updated.status.value
                    rec.updated_at = updated.updated_at
                    session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                if callable(self._session_factory):
                    session.close()

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
