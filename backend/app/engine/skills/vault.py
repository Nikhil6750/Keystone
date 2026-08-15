"""Stage 9C Obsidian Skill Vault Parser & Boundary-Enforcing Scanner.

Enforces strict vault boundaries:
- Canonical path checks against vault root.
- Rejects path traversal (..) and symlink escapes.
- Safe YAML loading with yaml.safe_load (rejects arbitrary python object tags).
- File size limit to protect against oversized files.
- Extracts frontmatter and markdown sections (When to use, Preconditions, Procedure, etc.).
"""

import contextlib
import os
import re
from pathlib import Path
from typing import Any

import yaml

from app.contracts.enums import AgentCapability
from app.contracts.skills import SkillCategory, SkillContract, SkillStatus
from app.engine.skills.errors import (
    MalformedSkillError,
    SkillValidationError,
    SkillVaultSecurityError,
)

MAX_SKILL_FILE_SIZE_BYTES = 512 * 1024  # 512 KB

_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?\n)?---[ \t]*\r?\n?", re.DOTALL)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def _safe_resolve_path(root: Path, relative_or_absolute: str | Path) -> Path:
    """Resolve a path safely inside `root`. Raises `SkillVaultSecurityError` if outside `root`."""
    root_resolved = root.resolve()
    target = (root / relative_or_absolute).resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as e:
        raise SkillVaultSecurityError(
            f"Access denied: path '{target}' escapes vault root '{root_resolved}'"
        ) from e
    return target


def parse_skill_markdown(
    raw_text: str,
    source_path: str = "memory",
    default_status: SkillStatus = SkillStatus.DRAFT,
) -> SkillContract:
    """Parse raw Markdown with YAML frontmatter into a typed `SkillContract`.

    Extracts standard sections:
    - # Title / Name
    - ## When to use / Description
    - ## Preconditions
    - ## Contraindications / Common failures / Pitfalls
    - ## Procedure
    - ## Verification / Verification Contract
    """
    if len(raw_text.encode("utf-8")) > MAX_SKILL_FILE_SIZE_BYTES:
        raise MalformedSkillError(
            f"Skill file exceeds max size limit of {MAX_SKILL_FILE_SIZE_BYTES} bytes"
        )

    frontmatter_match = _FRONTMATTER_RE.match(raw_text)
    frontmatter_yaml = ""
    body = raw_text

    if frontmatter_match:
        frontmatter_yaml = frontmatter_match.group(1) or ""
        body = raw_text[frontmatter_match.end() :]

    meta: dict[str, Any] = {}
    if frontmatter_yaml.strip():
        try:
            loaded = yaml.safe_load(frontmatter_yaml)
            if isinstance(loaded, dict):
                meta = loaded
        except yaml.YAMLError as e:
            raise MalformedSkillError(f"Malformed YAML frontmatter in '{source_path}': {e}") from e

    # Extract skill_id from frontmatter or filename
    skill_id = str(meta.get("skill_id", "")).strip()
    if not skill_id:
        path_stem = Path(source_path).stem
        skill_id = path_stem.lower().replace(" ", "-")
    if not skill_id:
        raise SkillValidationError(f"Cannot determine skill_id for skill from '{source_path}'")

    version = str(meta.get("version", "1.0.0")).strip()
    category_str = str(meta.get("category", SkillCategory.GENERAL.value)).strip()
    status_str = str(meta.get("status", default_status.value)).strip()

    # Parse sections from Markdown body
    sections: dict[str, str] = {}
    current_heading = "intro"
    current_lines: list[str] = []

    for line in body.splitlines():
        heading_match = re.match(r"^#{1,3}\s+(.+?)\s*$", line)
        if heading_match:
            if current_lines:
                sections[current_heading.lower()] = "\n".join(current_lines).strip()
                current_lines = []
            current_heading = heading_match.group(1).strip()
        else:
            current_lines.append(line)

    if current_lines:
        sections[current_heading.lower()] = "\n".join(current_lines).strip()

    # Extract name (from h1 or frontmatter or skill_id)
    name = str(meta.get("name", "")).strip()
    if not name:
        for k in sections:
            if not k.startswith("when") and not k.startswith("pre") and not k.startswith("proc"):
                # Potential title
                name = k.title()
                break
    if not name:
        name = skill_id.replace("-", " ").title()

    # Extract description
    description = str(meta.get("description", "")).strip()
    if not description:
        for key, val in sections.items():
            if "when to use" in key or "overview" in key or "description" in key or key == "intro":
                description = val
                break

    # Extract preconditions
    preconditions_raw = meta.get("preconditions", [])
    if isinstance(preconditions_raw, str):
        preconditions = tuple(p.strip() for p in preconditions_raw.splitlines() if p.strip())
    elif isinstance(preconditions_raw, list):
        preconditions = tuple(str(p).strip() for p in preconditions_raw if str(p).strip())
    else:
        preconditions = ()

    if not preconditions:
        for key, val in sections.items():
            if "precondition" in key:
                preconditions = tuple(
                    line.lstrip("-*0123456789. ").strip()
                    for line in val.splitlines()
                    if line.strip()
                )
                break

    # Extract contraindications / common failures / pitfalls
    contraindications_raw = meta.get("contraindications", [])
    if isinstance(contraindications_raw, str):
        contraindications = tuple(
            c.strip() for c in contraindications_raw.splitlines() if c.strip()
        )
    elif isinstance(contraindications_raw, list):
        contraindications = tuple(
            str(c).strip() for c in contraindications_raw if str(c).strip()
        )
    else:
        contraindications = ()

    if not contraindications:
        for key, val in sections.items():
            if any(term in key for term in ("contraindication", "pitfall", "common failure")):
                contraindications = tuple(
                    line.lstrip("-*0123456789. ").strip()
                    for line in val.splitlines()
                    if line.strip()
                )
                break

    # Extract procedure
    procedure = str(meta.get("procedure", "")).strip()
    if not procedure:
        for key, val in sections.items():
            if "procedure" in key or "steps" in key or "how to" in key or "instructions" in key:
                procedure = val
                break
    if not procedure and body.strip():
        procedure = body.strip()

    # Extract verification contract
    verification_contract = meta.get("verification_contract", {})
    if not isinstance(verification_contract, dict):
        verification_contract = {}

    if not verification_contract:
        for key, val in sections.items():
            if "verification" in key or key.strip() in ("tests", "testing", "validation"):
                verification_contract = {
                    "instructions": val,
                    "criteria": [
                        line.lstrip("-*0123456789. ").strip()
                        for line in val.splitlines()
                        if line.strip()
                    ],
                }
                break

    # Parse task types
    task_types_raw = meta.get("task_types", [])
    if isinstance(task_types_raw, str):
        task_types = tuple(t.strip() for t in task_types_raw.split(",") if t.strip())
    elif isinstance(task_types_raw, list):
        task_types = tuple(str(t).strip() for t in task_types_raw if str(t).strip())
    else:
        task_types = ()

    # Parse capabilities
    capabilities_raw = meta.get("capabilities", [])
    caps_list: list[AgentCapability] = []
    if isinstance(capabilities_raw, str):
        capabilities_raw = [c.strip() for c in capabilities_raw.split(",")]
    if isinstance(capabilities_raw, list):
        for c in capabilities_raw:
            with contextlib.suppress(ValueError):
                caps_list.append(AgentCapability(str(c).strip()))
    capabilities = tuple(caps_list)

    # Languages & Frameworks
    languages_raw = meta.get("languages", [])
    if isinstance(languages_raw, str):
        languages = tuple(item.strip() for item in languages_raw.split(",") if item.strip())
    elif isinstance(languages_raw, list):
        languages = tuple(str(item).strip() for item in languages_raw if str(item).strip())
    else:
        languages = ()

    frameworks_raw = meta.get("frameworks", [])
    if isinstance(frameworks_raw, str):
        frameworks = tuple(f.strip() for f in frameworks_raw.split(",") if f.strip())
    elif isinstance(frameworks_raw, list):
        frameworks = tuple(str(f).strip() for f in frameworks_raw if str(f).strip())
    else:
        frameworks = ()

    # Status
    try:
        status = SkillStatus(status_str.upper())
    except ValueError:
        status = default_status

    # Category
    category: SkillCategory | str = category_str
    with contextlib.suppress(ValueError):
        category = SkillCategory(category_str)

    provenance = meta.get("provenance", {})
    if not isinstance(provenance, dict):
        provenance = {}

    return SkillContract(
        skill_id=skill_id,
        version=version,
        name=name,
        description=description,
        category=category,
        task_types=task_types,
        capabilities=capabilities,
        languages=languages,
        frameworks=frameworks,
        preconditions=preconditions,
        contraindications=contraindications,
        procedure=procedure,
        verification_contract=verification_contract,
        source=source_path,
        provenance=provenance,
        status=status,
    )


def serialize_skill_to_markdown(skill: SkillContract) -> str:
    """Serialize a SkillContract into Obsidian-compatible Markdown with YAML frontmatter."""
    if isinstance(skill.category, SkillCategory):
        category_val = skill.category.value
    else:
        category_val = str(skill.category)

    frontmatter_dict: dict[str, Any] = {
        "skill_id": skill.skill_id,
        "version": skill.version,
        "name": skill.name,
        "status": skill.status.value,
        "category": category_val,
        "task_types": list(skill.task_types),
        "capabilities": [c.value for c in skill.capabilities],
        "languages": list(skill.languages),
        "frameworks": list(skill.frameworks),
    }
    if skill.preconditions:
        frontmatter_dict["preconditions"] = list(skill.preconditions)
    if skill.contraindications:
        frontmatter_dict["contraindications"] = list(skill.contraindications)
    if skill.provenance:
        frontmatter_dict["provenance"] = skill.provenance

    fm_yaml = yaml.dump(frontmatter_dict, sort_keys=False)

    lines = [
        "---",
        fm_yaml.strip(),
        "---",
        "",
        f"# {skill.name}",
        "",
        "## When to use",
        "",
        skill.description or "No description provided.",
        "",
        "## Preconditions",
        "",
    ]
    if skill.preconditions:
        for p in skill.preconditions:
            lines.append(f"- {p}")
    else:
        lines.append("- None specified")

    lines.extend([
        "",
        "## Contraindications and Common Failures",
        "",
    ])
    if skill.contraindications:
        for c in skill.contraindications:
            lines.append(f"- {c}")
    else:
        lines.append("- None specified")

    lines.extend([
        "",
        "## Procedure",
        "",
        skill.procedure or "No procedure specified.",
        "",
        "## Verification",
        "",
    ])
    if skill.verification_contract:
        if "instructions" in skill.verification_contract:
            lines.append(str(skill.verification_contract["instructions"]))
        if "criteria" in skill.verification_contract:
            criteria = skill.verification_contract["criteria"]
            if isinstance(criteria, list):
                for cr in criteria:
                    lines.append(f"- {cr}")
    else:
        lines.append("- Execute task verification checks")

    lines.append("")
    return "\n".join(lines)


class ObsidianSkillVault:
    """Manages reading and writing skills in an Obsidian-compatible Markdown vault."""

    def __init__(self, vault_root: Path | str) -> None:
        self.root = Path(vault_root).resolve()
        self._ensure_structure()

    def _ensure_structure(self) -> None:
        """Create standard vault directories if they don't exist."""
        subdirs = [
            "Skills/Backend",
            "Skills/Frontend",
            "Skills/Testing",
            "Skills/DataEngineering",
            "Skills/DevOps",
            "Skills/Debugging",
            "Candidates",
            "Deprecated",
            "Knowledge",
            "Evidence",
        ]
        for sub in subdirs:
            p = self.root / sub
            p.mkdir(parents=True, exist_ok=True)

    def scan_skills(self) -> tuple[list[SkillContract], list[tuple[str, str]]]:
        """Scan all markdown skill notes across the vault.

        Returns (valid_skills, errors).
        """
        valid_skills: list[SkillContract] = []
        errors: list[tuple[str, str]] = []

        if not self.root.exists() or not self.root.is_dir():
            return valid_skills, errors

        for dirpath, dirnames, filenames in os.walk(self.root):
            # Exclude hidden directories like .obsidian, .git
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]

            for filename in filenames:
                if not filename.endswith(".md"):
                    continue

                full_path = Path(dirpath) / filename
                rel_path = full_path.relative_to(self.root)

                # Check path safety
                try:
                    _safe_resolve_path(self.root, rel_path)
                except SkillVaultSecurityError as e:
                    errors.append((str(rel_path), str(e)))
                    continue

                try:
                    if full_path.stat().st_size > MAX_SKILL_FILE_SIZE_BYTES:
                        errors.append(
                            (
                                str(rel_path),
                                f"File exceeds size limit ({MAX_SKILL_FILE_SIZE_BYTES} bytes)",
                            )
                        )
                        continue

                    raw_text = full_path.read_text(encoding="utf-8")
                    skill = parse_skill_markdown(raw_text, source_path=str(rel_path))
                    valid_skills.append(skill)
                except Exception as e:
                    errors.append((str(rel_path), str(e)))

        return valid_skills, errors

    def write_skill(self, skill: SkillContract, directory: str | None = None) -> Path:
        """Write a skill to the vault safely."""
        if directory is None:
            if skill.status == SkillStatus.CANDIDATE:
                directory = "Candidates"
            elif skill.status == SkillStatus.DEPRECATED:
                directory = "Deprecated"
            else:
                if isinstance(skill.category, SkillCategory):
                    cat_name = skill.category.value
                else:
                    cat_name = str(skill.category)
                directory = f"Skills/{cat_name}"

        dest_dir = _safe_resolve_path(self.root, directory)
        dest_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{skill.skill_id}.md"
        dest_file = _safe_resolve_path(dest_dir, filename)

        content = serialize_skill_to_markdown(skill)
        dest_file.write_text(content, encoding="utf-8")
        return dest_file


__all__ = [
    "MAX_SKILL_FILE_SIZE_BYTES",
    "ObsidianSkillVault",
    "parse_skill_markdown",
    "serialize_skill_to_markdown",
]
