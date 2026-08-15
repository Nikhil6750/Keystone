"""Quality Plan Compiler: converts multi-source quality requirements
into a deterministic QualityPlan.

Precedence & Invariants:
1. Explicit Task / Outcome requirements (Highest precedence).
2. Skill Verification Contract recommendations.
3. Applicable QualityProfile (workflow/repository specific).
4. Repository / Language Default Profiles (Lowest precedence).

Anti-weakening Invariant:
If ANY layer designates a gate as `required=True`, lower or higher precedence merging
MUST NOT silently downgrade it to `required=False`.

Deduplication:
Duplicate gates matching `gate_id` are merged deterministically, preserving the strictest
timeout and requirement constraints. Output gates are deterministically ordered.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.contracts.planning import TaskSpec
from app.contracts.quality import (
    QualityGateSpec,
    QualityGateType,
    QualityProfile,
)
from app.contracts.skills import SkillContract


@dataclass(frozen=True)
class QualityPlan:
    """Compiled, deduplicated, ordered collection of quality gates to execute."""

    gates: tuple[QualityGateSpec, ...] = field(default_factory=tuple)
    profile_id: str | None = None

    def __post_init__(self) -> None:
        # Validate unique gate_ids in plan
        gate_ids = [g.gate_id for g in self.gates]
        if len(gate_ids) != len(set(gate_ids)):
            raise ValueError("QualityPlan contains duplicate gate_ids")


class QualityPlanCompiler:
    """Compiles software quality requirements from tasks, skills, profiles,
    and repository defaults.
    """

    def compile(
        self,
        task: TaskSpec | None = None,
        profile: QualityProfile | None = None,
        skill: SkillContract | None = None,
        workspace_languages: tuple[str, ...] | list[str] = (),
        workspace_frameworks: tuple[str, ...] | list[str] = (),
    ) -> QualityPlan:
        """Compile an ordered, deduplicated QualityPlan adhering to strict
        precedence and anti-weakening.
        """
        gate_map: dict[str, QualityGateSpec] = {}

        # 1. Base Layer: Default language-based gates if languages specified or baseline requested
        if workspace_languages or (profile is None and task is None and skill is None):
            default_gates = self._generate_default_gates(
                tuple(workspace_languages), tuple(workspace_frameworks)
            )
            for g in default_gates:
                gate_map[g.gate_id] = g

        # 2. Profile Layer: QualityProfile gates
        if profile is not None:
            for g in profile.gates:
                self._merge_gate(gate_map, g)

        # 3. Skill Layer: SkillContract verification_contract gates
        if skill is not None and skill.verification_contract:
            skill_gates = self._parse_skill_verification_contract(skill)
            for g in skill_gates:
                self._merge_gate(gate_map, g)

        # 4. Task Layer: Explicit task ExpectedOutcome & input_payload quality gates
        # (Highest precedence)
        if task is not None:
            task_gates = self._parse_task_quality_requirements(task)
            for g in task_gates:
                self._merge_gate(gate_map, g)

        # Deterministic sorting by (order, gate_id)
        sorted_gates = tuple(sorted(gate_map.values(), key=lambda g: (g.order, g.gate_id)))
        profile_id = profile.profile_id if profile else None

        return QualityPlan(gates=sorted_gates, profile_id=profile_id)

    def _merge_gate(self, gate_map: dict[str, QualityGateSpec], incoming: QualityGateSpec) -> None:
        """Merge an incoming gate spec with existing spec, enforcing anti-weakening."""
        if incoming.gate_id not in gate_map:
            gate_map[incoming.gate_id] = incoming
            return

        existing = gate_map[incoming.gate_id]
        # Anti-weakening: if EITHER existing or incoming is required, merged is REQUIRED
        merged_required = existing.required or incoming.required

        # Timeout: preserve stricter (smaller) positive timeout if both configured,
        # or incoming if non-default
        merged_timeout = min(existing.timeout_seconds, incoming.timeout_seconds)

        # Merge configurations additively
        merged_cfg = dict(existing.configuration)
        merged_cfg.update(incoming.configuration)

        gate_map[incoming.gate_id] = QualityGateSpec(
            gate_id=incoming.gate_id,
            gate_type=incoming.gate_type,
            name=incoming.name or existing.name,
            required=merged_required,
            timeout_seconds=merged_timeout,
            applicable_scope=incoming.applicable_scope or existing.applicable_scope,
            configuration=merged_cfg,
            order=min(existing.order, incoming.order),
        )

    def _generate_default_gates(
        self,
        languages: tuple[str, ...],
        frameworks: tuple[str, ...],
    ) -> list[QualityGateSpec]:
        """Generate baseline quality gates for recognized environments."""
        gates: list[QualityGateSpec] = []
        is_python = not languages or any(
            lang.lower() in ("python", "py") for lang in languages
        )
        is_js_ts = any(
            lang.lower() in ("javascript", "typescript", "node", "js", "ts") for lang in languages
        )

        if is_python:
            gates.append(
                QualityGateSpec(
                    gate_id="python-tests",
                    gate_type=QualityGateType.TEST,
                    name="Python Automated Tests",
                    required=True,
                    timeout_seconds=60.0,
                    order=10,
                )
            )
            gates.append(
                QualityGateSpec(
                    gate_id="python-lint",
                    gate_type=QualityGateType.LINT,
                    name="Python Code Quality (Ruff)",
                    required=True,
                    timeout_seconds=30.0,
                    order=20,
                )
            )
            gates.append(
                QualityGateSpec(
                    gate_id="python-types",
                    gate_type=QualityGateType.TYPE_CHECK,
                    name="Python Type Checking (MyPy)",
                    # Advisory by default in baseline, can be strengthened by profile/task
                    required=False,
                    timeout_seconds=45.0,
                    order=30,
                )
            )

        if is_js_ts:
            gates.append(
                QualityGateSpec(
                    gate_id="node-tests",
                    gate_type=QualityGateType.TEST,
                    name="Node.js Automated Tests",
                    required=True,
                    timeout_seconds=60.0,
                    order=10,
                )
            )
            gates.append(
                QualityGateSpec(
                    gate_id="node-lint",
                    gate_type=QualityGateType.LINT,
                    name="JavaScript / TypeScript Linter",
                    required=True,
                    timeout_seconds=30.0,
                    order=20,
                )
            )

        return gates

    def _parse_skill_verification_contract(self, skill: SkillContract) -> list[QualityGateSpec]:
        """Extract recommended quality gates from skill verification contract."""
        gates: list[QualityGateSpec] = []
        vc = skill.verification_contract or {}

        # Look for explicit quality_gates array or criteria
        if "quality_gates" in vc and isinstance(vc["quality_gates"], (list, tuple)):
            for g_def in vc["quality_gates"]:
                if isinstance(g_def, dict) and "gate_id" in g_def:
                    gates.append(
                        QualityGateSpec(
                            gate_id=str(g_def["gate_id"]),
                            gate_type=str(g_def.get("gate_type", "test")),
                            name=str(g_def.get("name", f"Skill Gate: {g_def['gate_id']}")),
                            required=bool(g_def.get("required", True)),
                            timeout_seconds=float(g_def.get("timeout_seconds", 30.0)),
                            configuration=dict(g_def.get("configuration", {})),
                            order=int(g_def.get("order", 15)),
                        )
                    )
        return gates

    def _parse_task_quality_requirements(self, task: TaskSpec) -> list[QualityGateSpec]:
        """Extract explicit quality gates from task outcome and payload specifications."""
        gates: list[QualityGateSpec] = []
        payload = task.input_payload or {}

        # 1. From payload quality_gates
        if "quality_gates" in payload and isinstance(payload["quality_gates"], (list, tuple)):
            for g_def in payload["quality_gates"]:
                if isinstance(g_def, dict) and "gate_id" in g_def:
                    gates.append(
                        QualityGateSpec(
                            gate_id=str(g_def["gate_id"]),
                            gate_type=str(g_def.get("gate_type", "test")),
                            name=str(g_def.get("name", f"Task Gate: {g_def['gate_id']}")),
                            required=bool(g_def.get("required", True)),
                            timeout_seconds=float(g_def.get("timeout_seconds", 30.0)),
                            configuration=dict(g_def.get("configuration", {})),
                            order=int(g_def.get("order", 5)),
                        )
                    )

        # 2. From expected_outcome evaluator_type
        if task.expected_outcome:
            eo = task.expected_outcome
            eval_type_str = (
                eo.evaluator_type.value
                if hasattr(eo.evaluator_type, "value")
                else str(eo.evaluator_type)
            )
            criteria = eo.criteria or {}

            # Map evaluator types to quality gate specs
            if eval_type_str in ("unit_test", "test"):
                gates.append(
                    QualityGateSpec(
                        gate_id=f"task-{task.key}-test",
                        gate_type=QualityGateType.TEST,
                        name=f"Task '{task.name}' Test Suite",
                        required=True,
                        timeout_seconds=float(criteria.get("timeout_seconds", 60.0)),
                        configuration=criteria,
                        order=1,
                    )
                )
            elif eval_type_str in ("lint", "static_analysis"):
                gates.append(
                    QualityGateSpec(
                        gate_id=f"task-{task.key}-lint",
                        gate_type=QualityGateType.LINT,
                        name=f"Task '{task.name}' Linter",
                        required=True,
                        timeout_seconds=float(criteria.get("timeout_seconds", 30.0)),
                        configuration=criteria,
                        order=2,
                    )
                )
            elif eval_type_str in ("type_check", "typecheck"):
                gates.append(
                    QualityGateSpec(
                        gate_id=f"task-{task.key}-typecheck",
                        gate_type=QualityGateType.TYPE_CHECK,
                        name=f"Task '{task.name}' Type Check",
                        required=True,
                        timeout_seconds=float(criteria.get("timeout_seconds", 45.0)),
                        configuration=criteria,
                        order=3,
                    )
                )
            elif eval_type_str in ("build", "compile"):
                gates.append(
                    QualityGateSpec(
                        gate_id=f"task-{task.key}-build",
                        gate_type=QualityGateType.BUILD,
                        name=f"Task '{task.name}' Build Check",
                        required=True,
                        timeout_seconds=float(criteria.get("timeout_seconds", 45.0)),
                        configuration=criteria,
                        order=4,
                    )
                )

        return gates


__all__ = ["QualityPlan", "QualityPlanCompiler"]
