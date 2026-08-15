"""Stage 9C Execution Prompt Integration & Skill Provenance Tracking.

Injects concise, bounded skill guidance into agent task execution prompts
without dumping raw whole files or exceeding token budgets.

Extracts:
- Skill Objective / Description
- Preconditions
- Key Procedure Steps
- Pitfalls & Contraindications
- Verification Contract
"""

from typing import Any

from app.contracts.skills import SkillContract


def build_bounded_skill_prompt_section(
    skill: SkillContract | None,
    max_procedure_chars: int = 1500,
) -> str:
    """Build a concise, bounded markdown section for inclusion in agent prompt."""
    if skill is None:
        return ""

    lines = [
        "### Verified Skill Guidance",
        (
            f"**Skill**: {skill.name} (ID: `{skill.skill_id}`, "
            f"v{skill.version}, Status: {skill.status.value})"
        ),
    ]

    if skill.description:
        lines.append(f"**Objective**: {skill.description}")

    if skill.preconditions:
        lines.append("**Preconditions**:")
        for p in skill.preconditions[:4]:  # Bounded
            lines.append(f"- {p}")

    if skill.contraindications:
        lines.append("**Pitfalls & Contraindications**:")
        for c in skill.contraindications[:4]:  # Bounded
            lines.append(f"- {c}")

    if skill.procedure:
        proc = skill.procedure.strip()
        if len(proc) > max_procedure_chars:
            proc = proc[:max_procedure_chars] + "... [truncated for brevity]"
        lines.append("**Procedure Steps**:")
        lines.append(proc)

    if skill.verification_contract:
        lines.append("**Verification Criteria**:")
        if "criteria" in skill.verification_contract:
            criteria = skill.verification_contract["criteria"]
            if isinstance(criteria, list):
                for cr in criteria[:4]:  # Bounded
                    lines.append(f"- {cr}")
        elif "instructions" in skill.verification_contract:
            lines.append(f"- {skill.verification_contract['instructions']}")

    lines.append("")
    return "\n".join(lines)


def attach_skill_to_task_payload(
    input_payload: dict[str, Any],
    skill: SkillContract | None,
    execution_id: str,
    task_id: str,
) -> dict[str, Any]:
    """Inject bounded skill prompt and provenance into a task's input payload."""
    payload = dict(input_payload)
    if skill is None:
        payload.setdefault("skill_guidance", "")
        return payload

    skill_section = build_bounded_skill_prompt_section(skill)

    payload["skill_guidance"] = skill_section
    payload["skill_provenance"] = {
        "execution_id": execution_id,
        "task_id": task_id,
        "skill_id": skill.skill_id,
        "skill_version": skill.version,
        "skill_status": skill.status.value,
    }

    # If prompt exists, enrich it with skill guidance
    if skill_section and "objective" in payload:
        payload["objective_with_skill"] = f"{payload['objective']}\n\n{skill_section}"

    return payload


__all__ = [
    "attach_skill_to_task_payload",
    "build_bounded_skill_prompt_section",
]
