"""Deterministic unit tests for prompt integration, TaskGraph compiler independence,
and orchestration.
"""

from app.contracts.enums import AgentCapability
from app.contracts.planning import TaskSpec
from app.contracts.skills import SkillCategory, SkillContract, SkillStatus
from app.contracts.verification import VerificationStatus
from app.engine.planning.compiler import TaskGraphCompilerV2
from app.engine.skills.evidence import InMemorySkillEvidenceRepository
from app.engine.skills.orchestration_adapter import SkillOrchestrationCoordinator
from app.engine.skills.prompt_integration import (
    build_bounded_skill_prompt_section,
)
from app.engine.skills.registry import SkillRegistry


def test_task_graph_compiles_independently_with_zero_skills() -> None:
    compiler = TaskGraphCompilerV2()
    # Decompose a goal with zero skills installed
    plan = compiler.compile("Build a small FastAPI backend with pytest suite")
    assert len(plan) >= 1

    # TaskGraph nodes have no hardcoded agent assignments
    for task in plan:
        assert task.task_id
        assert task.task_type


def test_bounded_skill_prompt_generation() -> None:
    skill = SkillContract(
        skill_id="fastapi-crud-endpoint",
        version="1.0.0",
        name="FastAPI CRUD Endpoint",
        description="Creates RESTful CRUD endpoints in FastAPI",
        category=SkillCategory.BACKEND,
        task_types=("api_implementation",),
        capabilities=(AgentCapability.CODE_GENERATION,),
        preconditions=("Python 3.11+", "Dependencies installed"),
        contraindications=("Do not use global mutable state",),
        procedure="1. Define router\n2. Add GET/POST handlers\n3. Add schema validation",
        verification_contract={
            "criteria": ["HTTP 200/201 responses", "Pydantic validation passes"]
        },
        status=SkillStatus.VERIFIED,
    )

    prompt_section = build_bounded_skill_prompt_section(skill)
    assert "### Verified Skill Guidance" in prompt_section
    assert "FastAPI CRUD Endpoint" in prompt_section
    assert "Do not use global mutable state" in prompt_section
    assert "HTTP 200/201 responses" in prompt_section


def test_orchestration_coordinator_skill_attachment_and_provenance() -> None:
    registry = SkillRegistry()
    evidence_repo = InMemorySkillEvidenceRepository()

    skill = SkillContract(
        skill_id="python-api-endpoint",
        version="1.0.0",
        name="Python API Endpoint",
        description="Implements Python API endpoints",
        category=SkillCategory.BACKEND,
        task_types=("api_implementation",),
        capabilities=(AgentCapability.CODE_GENERATION, AgentCapability.FILE_EDITING),
        languages=("python",),
        status=SkillStatus.VERIFIED,
    )
    registry.register_skill(skill)

    coordinator = SkillOrchestrationCoordinator(registry=registry, evidence_repo=evidence_repo)

    tasks = [
        TaskSpec(
            key="task-1",
            name="Implement User API",
            task_type="api_implementation",
            required_capabilities=[AgentCapability.CODE_GENERATION, AgentCapability.FILE_EDITING],
            input_payload={"objective": "Implement user endpoints"},
        ),
        TaskSpec(
            key="task-2",
            name="Generic task without skill",
            task_type="custom_task_type",
            required_capabilities=[AgentCapability.CODE_GENERATION],
            input_payload={"objective": "Perform custom work"},
        ),
    ]

    enriched = coordinator.enrich_task_specs_with_skills(
        task_specs=tasks,
        workspace_context={"languages": ["python"]},
        execution_id="exec-42",
    )

    assert len(enriched) == 2
    # Task 1 has skill attached with provenance
    payload_1 = enriched[0].input_payload or {}
    assert "skill_guidance" in payload_1
    assert payload_1["skill_provenance"]["skill_id"] == "python-api-endpoint"
    assert payload_1["skill_provenance"]["execution_id"] == "exec-42"
    assert payload_1["skill_provenance"]["task_id"] == "task-1"

    # Task 2 has no matching skill
    payload_2 = enriched[1].input_payload or {}
    assert payload_2.get("skill_guidance") == ""

    # Record execution outcome
    coordinator.record_execution_outcome(
        skill_id="python-api-endpoint",
        skill_version="1.0.0",
        task_type="api_implementation",
        agent_id="codex",
        execution_id="exec-42",
        task_id="task-1",
        verification_status=VerificationStatus.PASSED,
        latency_ms=120.0,
        objective="Implement user endpoints",
    )

    # Check evidence recorded
    ev_records = evidence_repo.get_evidence_for_skill("python-api-endpoint")
    assert len(ev_records) == 1
    assert ev_records[0].success is True
    assert ev_records[0].agent_id == "codex"
