"""Unit tests for Stage 9D QualityPlanCompiler and Precedence Rules."""

from app.contracts.enums import BenchmarkEvaluatorType
from app.contracts.planning import ExpectedOutcome, TaskSpec
from app.contracts.quality import (
    QualityGateSpec,
    QualityGateType,
    QualityProfile,
)
from app.contracts.skills import SkillContract
from app.engine.quality.compiler import QualityPlanCompiler


def test_quality_plan_compiler_defaults_generation() -> None:
    compiler = QualityPlanCompiler()
    plan = compiler.compile(workspace_languages=("python",))
    assert len(plan.gates) == 3
    gate_ids = [g.gate_id for g in plan.gates]
    assert "python-tests" in gate_ids
    assert "python-lint" in gate_ids
    assert "python-types" in gate_ids


def test_quality_plan_compiler_precedence_and_anti_weakening() -> None:
    compiler = QualityPlanCompiler()

    # 1. Profile defines python-types as required=True
    profile = QualityProfile(
        profile_id="strict-profile",
        name="Strict Profile",
        gates=(
            QualityGateSpec(
                gate_id="python-types",
                gate_type=QualityGateType.TYPE_CHECK,
                name="Strict Types",
                required=True,
                timeout_seconds=30.0,
            ),
        ),
    )

    # 2. Skill has python-types as required=False (cannot weaken profile's required=True!)
    skill = SkillContract(
        skill_id="py-skill",
        version="1.0.0",
        name="Python Skill",
        description="A python skill",
        category="Backend",
        verification_contract={
            "quality_gates": [
                {
                    "gate_id": "python-types",
                    "gate_type": "type_check",
                    "required": False,
                    "timeout_seconds": 60.0,
                }
            ]
        },
    )

    plan = compiler.compile(
        profile=profile,
        skill=skill,
        workspace_languages=("python",),
    )

    # Find merged python-types gate
    types_gate = next(g for g in plan.gates if g.gate_id == "python-types")
    # Must remain required=True due to anti-weakening invariant!
    assert types_gate.required is True
    # Timeout must preserve the stricter (smaller) positive value 30.0
    assert types_gate.timeout_seconds == 30.0


def test_quality_plan_compiler_task_outcome_integration() -> None:
    compiler = QualityPlanCompiler()

    task = TaskSpec(
        key="build-task",
        name="Build API",
        task_type="backend_development",
        expected_outcome=ExpectedOutcome(
            evaluator_type=BenchmarkEvaluatorType.BUILD,
            criteria={"target_path": "src", "timeout_seconds": 50.0},
        ),
        input_payload={
            "quality_gates": [
                {
                    "gate_id": "custom-security-scan",
                    "gate_type": "custom",
                    "name": "Security Scan",
                    "required": True,
                    "timeout_seconds": 20.0,
                    "configuration": {"argv": ["python", "--version"]},
                }
            ]
        },
    )

    plan = compiler.compile(task=task, workspace_languages=("python",))
    gate_ids = [g.gate_id for g in plan.gates]
    assert "task-build-task-build" in gate_ids
    assert "custom-security-scan" in gate_ids


def test_quality_plan_compiler_deterministic_ordering() -> None:
    compiler = QualityPlanCompiler()

    g1 = QualityGateSpec(gate_id="gate-b", gate_type=QualityGateType.TEST, name="B", order=20)
    g2 = QualityGateSpec(gate_id="gate-a", gate_type=QualityGateType.TEST, name="A", order=20)
    g3 = QualityGateSpec(
        gate_id="gate-early", gate_type=QualityGateType.BUILD, name="Early", order=5
    )

    profile = QualityProfile(
        profile_id="order-profile",
        name="Order Profile",
        gates=(g1, g2, g3),
    )

    plan1 = compiler.compile(profile=profile)
    plan2 = compiler.compile(profile=profile)

    # Identical ordering guaranteed: order=5 first, then alphabetical gate_id for tie-breaking
    assert [g.gate_id for g in plan1.gates] == [g.gate_id for g in plan2.gates]
    assert plan1.gates[0].gate_id == "gate-early"
    assert plan1.gates[1].gate_id == "gate-a"
    assert plan1.gates[2].gate_id == "gate-b"
