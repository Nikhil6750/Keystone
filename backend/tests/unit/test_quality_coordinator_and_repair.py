"""Unit tests for QualityFactoryCoordinator and QualityRepairManager."""

import tempfile

from app.contracts.quality import (
    QualityExecutionContext,
    QualityGateResult,
    QualityGateSpec,
    QualityGateStatus,
    QualityGateType,
    QualityProfile,
    QualityRun,
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
            workflow_id="wf-1",
            attempt_number=3,
        )
        assert verdict.passed is False
        packet = coord.create_repair_packet(run, max_repair_attempts=3)
        assert packet is None


def test_coordinator_malformed_configuration_fails_closed() -> None:
    repo = InMemoryQualityRepository()
    coord = QualityFactoryCoordinator(repository=repo)

    with tempfile.TemporaryDirectory() as temp_dir:
        context = QualityExecutionContext(workspace_root=temp_dir, task_id="task-malformed")
        # Pass a custom plan with invalid gate configuration
        from app.contracts.planning import TaskSpec

        task_malformed = TaskSpec(
            key="T1",
            name="Malformed Task",
            task_type="code_generation",
            input_payload={"quality_gates": [{"gate_id": "bad-gate", "gate_type": "   "}]},
        )
        verdict, run = coord.verify_software_execution(
            context=context,
            task=task_malformed,
        )
        assert verdict.status == QualityVerdictStatus.ERROR
        assert verdict.passed is False
        assert len(run.gate_results) >= 1
        assert "Malformed quality contract or configuration" in (
            run.gate_results[0].failure_reason or ""
        )


def test_coordinator_empty_plan_fails_closed() -> None:
    repo = InMemoryQualityRepository()
    coord = QualityFactoryCoordinator(repository=repo)

    with tempfile.TemporaryDirectory() as temp_dir:
        context = QualityExecutionContext(workspace_root=temp_dir, task_id="task-empty")
        empty_profile = QualityProfile(
            profile_id="empty-prof",
            name="Empty Profile",
            gates=(),
        )
        verdict, run = coord.verify_software_execution(
            context=context,
            profile=empty_profile,
        )
        assert verdict.status == QualityVerdictStatus.REJECTED
        assert verdict.passed is False
        assert "NO_APPLICABLE_QUALITY_GATES" in verdict.summary_explanation


def test_coordinator_persistence_failure_blocks_acceptance() -> None:
    class FailingQualityRepository:
        def save_profile(self, profile: QualityProfile) -> None:
            pass

        def get_profile(self, profile_id: str) -> QualityProfile | None:
            return None

        def get_default_profile(self) -> QualityProfile | None:
            return None

        def list_profiles(self) -> list[QualityProfile]:
            return []

        def save_run(self, run: QualityRun) -> None:
            raise RuntimeError("Database connection lost during save_run")

        def get_run(self, run_id: str) -> QualityRun | None:
            return None

        def get_runs_by_execution(self, execution_id: str) -> list[QualityRun]:
            return []

        def get_runs_by_task(self, task_id: str) -> list[QualityRun]:
            return []

        def get_runs_by_workflow(self, workflow_id: str) -> list[QualityRun]:
            return []

        def get_gate_results_for_run(self, run_id: str) -> list[QualityGateResult]:
            return []

        def get_latest_run_for_task(
            self, task_id: str, execution_id: str | None = None
        ) -> QualityRun | None:
            return None

    registry = QualityGateExecutorRegistry()
    mock_exec = MockQualityGateExecutor(default_status=QualityGateStatus.PASSED)
    registry.register_executor(QualityGateType.TEST, mock_exec)

    coord = QualityFactoryCoordinator(
        repository=FailingQualityRepository(),  # type: ignore[arg-type]
        registry=registry,
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        context = QualityExecutionContext(workspace_root=temp_dir, task_id="task-persist-fail")
        profile = QualityProfile(
            profile_id="test-prof",
            name="Profile",
            gates=(
                QualityGateSpec(gate_id="g-test", gate_type=QualityGateType.TEST, name="Tests"),
            ),
        )

        verdict, run = coord.verify_software_execution(
            context=context,
            profile=profile,
        )

        # Persistence failure MUST fail closed: status=ERROR, passed=False,
        # run_id marked unpersisted
        assert verdict.status == QualityVerdictStatus.ERROR
        assert verdict.passed is False
        assert "Quality persistence failure" in verdict.summary_explanation
        assert run.run_id.startswith("unpersisted-")
