"""Unit tests for QualityFactoryCoordinator and QualityRepairManager."""

import tempfile

from app.contracts.quality import (
    QualityExecutionContext,
    QualityGateSpec,
    QualityGateStatus,
    QualityGateType,
    QualityProfile,
    QualityVerdictStatus,
)
from app.engine.quality.coordinator import QualityFactoryCoordinator
from app.engine.quality.executors import MockQualityGateExecutor
from app.engine.quality.registry import QualityGateExecutorRegistry
from app.engine.quality.repair import QualityRepairManager
from app.engine.quality.repository import InMemoryQualityRepository


def test_coordinator_verification_flow_pass() -> None:
    repo = InMemoryQualityRepository()
    registry = QualityGateExecutorRegistry()
    mock_exec = MockQualityGateExecutor(default_status=QualityGateStatus.PASSED)
    registry.register_executor(QualityGateType.TEST, mock_exec)
    registry.register_executor(QualityGateType.LINT, mock_exec)

    coord = QualityFactoryCoordinator(repository=repo, registry=registry)

    with tempfile.TemporaryDirectory() as temp_dir:
        context = QualityExecutionContext(workspace_root=temp_dir, task_id="task-1")
        profile = QualityProfile(
            profile_id="test-prof",
            name="Profile",
            gates=(
                QualityGateSpec(gate_id="g-test", gate_type=QualityGateType.TEST, name="Tests"),
                QualityGateSpec(gate_id="g-lint", gate_type=QualityGateType.LINT, name="Lint"),
            ),
        )

        verdict, run = coord.verify_software_execution(
            context=context,
            profile=profile,
            workflow_id="wf-1",
            attempt_number=1,
        )

        assert verdict.status == QualityVerdictStatus.ACCEPTED
        assert verdict.passed is True
        assert len(run.gate_results) == 2
        assert repo.get_run(run.run_id) is not None


def test_coordinator_verification_flow_failure_and_repair_packet() -> None:
    repo = InMemoryQualityRepository()
    registry = QualityGateExecutorRegistry()

    mock_exec = MockQualityGateExecutor(
        default_status=QualityGateStatus.FAILED,
        custom_evidence={
            "g-test": {
                "summary": "2 tests failed in test_calc.py",
                "diagnostics": ["AssertionError: calc(2, 2) != 5"],
                "artifact_references": ["src/calc.py"],
            }
        },
    )
    registry.register_executor(QualityGateType.TEST, mock_exec)

    repair_manager = QualityRepairManager()
    coord = QualityFactoryCoordinator(
        repository=repo, registry=registry, repair_manager=repair_manager
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        context = QualityExecutionContext(workspace_root=temp_dir, task_id="task-calc")
        profile = QualityProfile(
            profile_id="test-prof",
            name="Profile",
            gates=(
                QualityGateSpec(
                    gate_id="g-test",
                    gate_type=QualityGateType.TEST,
                    name="Calculator Tests",
                    required=True,
                ),
            ),
        )

        verdict, run = coord.verify_software_execution(
            context=context,
            profile=profile,
            workflow_id="wf-1",
            attempt_number=1,
        )

        assert verdict.status == QualityVerdictStatus.REJECTED
        assert verdict.passed is False

        # Build repair packet
        packet = coord.create_repair_packet(run, max_repair_attempts=3)
        assert packet is not None
        assert packet.attempt_number == 1
        assert packet.max_repair_attempts == 3
        assert "g-test" in packet.blocking_gate_ids
        assert len(packet.diagnostics) == 1
        assert "AssertionError: calc(2, 2) != 5" in packet.diagnostics[0]
        assert "src/calc.py" in packet.affected_artifacts

        # Check formatted repair prompt section
        prompt_sec = QualityRepairManager.format_repair_prompt_section(packet)
        assert "REQUIRED QUALITY VERIFICATION REPAIR NOTICE" in prompt_sec
        assert "AssertionError: calc(2, 2) != 5" in prompt_sec
        assert "src/calc.py" in prompt_sec


def test_repair_packet_attempts_exhaustion() -> None:
    repair_manager = QualityRepairManager()

    with tempfile.TemporaryDirectory() as temp_dir:
        repo = InMemoryQualityRepository()
        registry = QualityGateExecutorRegistry()
        mock_exec = MockQualityGateExecutor(default_status=QualityGateStatus.FAILED)
        registry.register_executor(QualityGateType.TEST, mock_exec)
        coord = QualityFactoryCoordinator(
            repository=repo, registry=registry, repair_manager=repair_manager
        )

        context = QualityExecutionContext(workspace_root=temp_dir, task_id="task-exhaust")
        profile = QualityProfile(
            profile_id="test-prof",
            name="Profile",
            gates=(
                QualityGateSpec(
                    gate_id="g-test", gate_type=QualityGateType.TEST, name="Tests", required=True
                ),
            ),
        )

        # Attempt 3 of 3 -> no further repair packets allowed
        verdict, run = coord.verify_software_execution(
            context=context,
            profile=profile,
            attempt_number=3,
        )
        packet = coord.create_repair_packet(run, max_repair_attempts=3)
        assert packet is None
