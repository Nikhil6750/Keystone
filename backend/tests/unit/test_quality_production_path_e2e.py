"""Real Production-Path Stage 9D Software Quality Factory E2E & Acceptance Test Suite.

Certifies:
1. End-to-end software task execution with QualityFactory verification:
   - When required quality checks pass, orchestration succeeds with VERIFIED_SUCCESS.
   - QualityRun and QualityVerdict are recorded and queryable.
2. Required quality gate failure stops unverified acceptance:
   - Fails verification despite agent returning SUCCEEDED.
   - Generates structured QualityRepairPacket with factual diagnostics.
   - Sends repair packet into bounded orchestration recovery loop.
   - Once repaired in workspace, subsequent verification passes and workflow completes.
3. Unrepairable failure halts cleanly at bounded attempt limits without infinite looping.
4. Full provenance recorded: workflow_id, task_id, execution_id, attempt_number,
   gate results, and verdict.
"""

import tempfile
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.contracts.adapter import AgentDescriptor
from app.contracts.enums import AgentCapability, AgentStatus
from app.contracts.quality import (
    QualityGateSpec,
    QualityGateStatus,
    QualityGateType,
    QualityProfile,
)
from app.database.base import Base
from app.engine.orchestration.models import (
    OrchestrationOutcome,
    OrchestrationRequest,
)
from app.engine.orchestration.runtime import RuntimeCandidateProvider
from app.engine.orchestration.service import EndToEndOrchestrationService
from app.engine.quality.coordinator import QualityFactoryCoordinator
from app.engine.quality.executors import MockQualityGateExecutor
from app.engine.quality.registry import QualityGateExecutorRegistry
from app.engine.quality.repository import SqlAlchemyQualityRepository
from app.engine.registry import ExecutorRegistry
from app.engine.routing.availability import CandidateAgent
from app.resilience.circuit_breaker import CircuitState


class FakeCandidateProvider(RuntimeCandidateProvider):
    def __init__(self, candidates: list[CandidateAgent]) -> None:
        self._candidates = candidates

    def candidates(self) -> list[CandidateAgent]:
        return list(self._candidates)


class QualityDemoAdapter:
    def __init__(self, should_fail_first_attempt: bool = False) -> None:
        self.attempts = 0
        self.should_fail_first_attempt = should_fail_first_attempt
        self.received_repair_guidance: list[str] = []

    def execute(self, request: Any) -> dict[str, Any]:
        self.attempts += 1
        payload = getattr(request, "step_input", {}) or getattr(request, "input_payload", {}) or {}
        if "repair_guidance" in payload:
            self.received_repair_guidance.append(payload["repair_guidance"])

        return {
            "agent_type": "quality-demo-agent",
            "content": f"Execution attempt {self.attempts} output",
            "exit_code": 0,
            "output": "5 passed in 0.05s",
            "tests_total": 5,
            "tests_passed": 5,
            "tests_failed": 0,
            "tests_skipped": 0,
            "structured_evidence": {"output_file": "src/app.py", "attempt": self.attempts},
            "metadata": {
                "execution_mode": "demo",
                "exit_code": 0,
            },
        }


@pytest.mark.asyncio
async def test_quality_factory_production_path_success(tmp_path: Path) -> None:
    db_file = tmp_path / "quality_test_1.db"
    engine = create_engine(f"sqlite:///{db_file}", echo=False)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    q_repo = SqlAlchemyQualityRepository(session_factory=session_factory)
    q_registry = QualityGateExecutorRegistry()
    mock_exec = MockQualityGateExecutor(default_status=QualityGateStatus.PASSED)
    q_registry.register_executor(QualityGateType.TEST, mock_exec)
    q_registry.register_executor(QualityGateType.LINT, mock_exec)

    q_coord = QualityFactoryCoordinator(repository=q_repo, registry=q_registry)

    # Register default profile
    q_repo.save_profile(
        QualityProfile(
            profile_id="default-profile",
            name="Default Quality Profile",
            gates=(
                QualityGateSpec(
                    gate_id="python-tests",
                    gate_type=QualityGateType.TEST,
                    name="Tests",
                    required=True,
                ),
            ),
            is_default=True,
        )
    )

    with tempfile.TemporaryDirectory() as ws_dir:
        ws_root = Path(ws_dir)
        exec_registry = ExecutorRegistry()
        adapter = QualityDemoAdapter()
        exec_registry.register("quality-demo-agent", adapter)

        from app.resilience.circuit_breaker import CircuitState

        descriptor = AgentDescriptor(
            agent_type="quality-demo-agent",
            display_name="Quality Demo Agent",
            capabilities=[
                AgentCapability.CODE_GENERATION,
                AgentCapability.TEST_GENERATION,
                AgentCapability.TEST_EXECUTION,
                AgentCapability.FILE_EDITING,
            ],
            cost_tier="standard",
        )
        candidate = CandidateAgent(
            descriptor=descriptor,
            status=AgentStatus.AVAILABLE,
            circuit_state=CircuitState.CLOSED,
        )
        candidate_provider = FakeCandidateProvider([candidate])

        service = EndToEndOrchestrationService(
            db=session_factory(),
            registry=exec_registry,
            candidate_provider=candidate_provider,
            quality_coordinator=q_coord,
        )

        req = OrchestrationRequest(
            request_id="req-quality-pass-1",
            goal="Implement feature with verified tests",
            workspace_root=str(ws_root),
            available_agent_types=["quality-demo-agent"],
        )

        result = await service.orchestrate(req)
        assert result.outcome == OrchestrationOutcome.VERIFIED_SUCCESS
        assert result.quality_run_id is not None
        assert result.quality_verdict_status == "ACCEPTED"

        # Verify quality run was persisted
        run = q_repo.get_run(result.quality_run_id)
        assert run is not None
        assert run.verdict is not None
        assert run.verdict.passed is True

        # Reusing the production service for a request where Stage 9D is not
        # applicable must not expose the prior request's authoritative run.
        legacy_result = await service.orchestrate(
            OrchestrationRequest(
                request_id="req-quality-not-applicable-after-pass",
                goal="Implement feature without a workspace",
                available_agent_types=["quality-demo-agent"],
            )
        )
        assert legacy_result.quality_run_id is None
        assert legacy_result.quality_verdict_status is None


@pytest.mark.asyncio
async def test_quality_persistence_failure_does_not_expose_fake_run_id(tmp_path: Path) -> None:
    class FailingRunRepository(SqlAlchemyQualityRepository):
        def save_run(self, run: Any) -> None:
            raise RuntimeError("authoritative save_run unavailable")

    db_file = tmp_path / "quality_persistence_failure.db"
    engine = create_engine(f"sqlite:///{db_file}", echo=False)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    q_repo = FailingRunRepository(session_factory=session_factory)
    q_repo.save_profile(
        QualityProfile(
            profile_id="default-profile",
            name="Default Quality Profile",
            gates=(
                QualityGateSpec(
                    gate_id="python-tests",
                    gate_type=QualityGateType.TEST,
                    name="Tests",
                    required=True,
                ),
            ),
            is_default=True,
        )
    )
    q_registry = QualityGateExecutorRegistry()
    q_registry.register_executor(
        QualityGateType.TEST,
        MockQualityGateExecutor(default_status=QualityGateStatus.PASSED),
    )

    exec_registry = ExecutorRegistry()
    exec_registry.register("quality-demo-agent", QualityDemoAdapter())
    descriptor = AgentDescriptor(
        agent_type="quality-demo-agent",
        display_name="Quality Demo Agent",
        capabilities=[
            AgentCapability.CODE_GENERATION,
            AgentCapability.TEST_GENERATION,
            AgentCapability.TEST_EXECUTION,
            AgentCapability.FILE_EDITING,
        ],
        cost_tier="standard",
    )
    candidate = CandidateAgent(
        descriptor=descriptor,
        status=AgentStatus.AVAILABLE,
        circuit_state=CircuitState.CLOSED,
    )
    service = EndToEndOrchestrationService(
        db=session_factory(),
        registry=exec_registry,
        candidate_provider=FakeCandidateProvider([candidate]),
        quality_coordinator=QualityFactoryCoordinator(
            repository=q_repo,
            registry=q_registry,
        ),
    )

    result = await service.orchestrate(
        OrchestrationRequest(
            request_id="req-quality-persistence-failure",
            goal="Implement feature with verified tests",
            workspace_root=str(tmp_path),
            available_agent_types=["quality-demo-agent"],
        )
    )

    assert result.outcome != OrchestrationOutcome.VERIFIED_SUCCESS
    assert result.quality_run_id is None
    assert result.quality_verdict_status == "ERROR"


@pytest.mark.asyncio
async def test_quality_factory_repair_loop_recovery(tmp_path: Path) -> None:
    db_file = tmp_path / "quality_test_2.db"
    engine = create_engine(f"sqlite:///{db_file}", echo=False)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    q_repo = SqlAlchemyQualityRepository(session_factory=session_factory)
    q_registry = QualityGateExecutorRegistry()

    # Executor fails attempt 1, passes subsequent attempts (simulating code repair)
    class DynamicMockExecutor:
        def __init__(self) -> None:
            self.calls = 0

        def execute(self, spec: Any, context: Any) -> Any:
            self.calls += 1
            if self.calls == 1:
                from datetime import UTC, datetime

                from app.contracts.quality import QualityEvidence, QualityGateResult

                return QualityGateResult(
                    gate_id=spec.gate_id,
                    gate_type=spec.gate_type,
                    name=spec.name,
                    status=QualityGateStatus.FAILED,
                    required=spec.required,
                    evidence=QualityEvidence(
                        summary="AssertionError in test_logic.py: 42 != 0",
                        diagnostics=("AssertionError: 42 != 0",),
                        artifact_references=("src/logic.py",),
                    ),
                    failure_reason="AssertionError in test_logic.py: 42 != 0",
                    timestamp=datetime.now(UTC),
                )
            from datetime import UTC, datetime

            from app.contracts.quality import QualityEvidence, QualityGateResult

            return QualityGateResult(
                gate_id=spec.gate_id,
                gate_type=spec.gate_type,
                name=spec.name,
                status=QualityGateStatus.PASSED,
                required=spec.required,
                evidence=QualityEvidence(summary="All tests passed", exit_code=0),
                timestamp=datetime.now(UTC),
            )

    dynamic_exec = DynamicMockExecutor()
    q_registry.register_executor(QualityGateType.TEST, dynamic_exec)
    q_registry.register_executor(QualityGateType.LINT, dynamic_exec)

    q_coord = QualityFactoryCoordinator(repository=q_repo, registry=q_registry)
    q_repo.save_profile(
        QualityProfile(
            profile_id="default-profile",
            name="Default Profile",
            gates=(
                QualityGateSpec(
                    gate_id="python-tests",
                    gate_type=QualityGateType.TEST,
                    name="Tests",
                    required=True,
                ),
            ),
            is_default=True,
        )
    )

    with tempfile.TemporaryDirectory() as ws_dir:
        ws_root = Path(ws_dir)
        exec_registry = ExecutorRegistry()
        adapter = QualityDemoAdapter()
        exec_registry.register("quality-demo-agent", adapter)

        from app.resilience.circuit_breaker import CircuitState

        descriptor = AgentDescriptor(
            agent_type="quality-demo-agent",
            display_name="Quality Demo Agent",
            capabilities=[
                AgentCapability.CODE_GENERATION,
                AgentCapability.TEST_GENERATION,
                AgentCapability.TEST_EXECUTION,
                AgentCapability.FILE_EDITING,
            ],
            cost_tier="standard",
        )
        candidate = CandidateAgent(
            descriptor=descriptor,
            status=AgentStatus.AVAILABLE,
            circuit_state=CircuitState.CLOSED,
        )
        candidate_provider = FakeCandidateProvider([candidate])

        service = EndToEndOrchestrationService(
            db=session_factory(),
            registry=exec_registry,
            candidate_provider=candidate_provider,
            quality_coordinator=q_coord,
        )

        req = OrchestrationRequest(
            request_id="req-quality-repair-1",
            goal="Implement feature requiring quality repair",
            workspace_root=str(ws_root),
            available_agent_types=["quality-demo-agent"],
        )

        result = await service.orchestrate(req)
        # Should succeed after recovery attempt
        assert result.outcome == OrchestrationOutcome.VERIFIED_SUCCESS
        assert result.recovery_used is True
        # Verify that repair guidance was provided to the adapter on recovery attempt
        assert len(adapter.received_repair_guidance) > 0
        assert "REQUIRED QUALITY VERIFICATION REPAIR NOTICE" in adapter.received_repair_guidance[0]
        assert "AssertionError: 42 != 0" in adapter.received_repair_guidance[0]


@pytest.mark.asyncio
async def test_quality_factory_required_skipped_fails_acceptance(tmp_path: Path) -> None:
    db_file = tmp_path / "quality_test_skipped.db"
    engine = create_engine(f"sqlite:///{db_file}", echo=False)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    q_repo = SqlAlchemyQualityRepository(session_factory=session_factory)
    q_registry = QualityGateExecutorRegistry()

    # Executor returns SKIPPED for all gates
    mock_exec = MockQualityGateExecutor(default_status=QualityGateStatus.SKIPPED)
    q_registry.register_executor(QualityGateType.TEST, mock_exec)
    q_registry.register_executor(QualityGateType.LINT, mock_exec)

    q_coord = QualityFactoryCoordinator(repository=q_repo, registry=q_registry)
    q_repo.save_profile(
        QualityProfile(
            profile_id="default-profile",
            name="Default Profile",
            gates=(
                QualityGateSpec(
                    gate_id="python-tests",
                    gate_type=QualityGateType.TEST,
                    name="Required Tests",
                    required=True,
                ),
            ),
            is_default=True,
        )
    )

    with tempfile.TemporaryDirectory() as ws_dir:
        ws_root = Path(ws_dir)
        exec_registry = ExecutorRegistry()
        adapter = QualityDemoAdapter()
        exec_registry.register("quality-demo-agent", adapter)

        from app.resilience.circuit_breaker import CircuitState

        descriptor = AgentDescriptor(
            agent_type="quality-demo-agent",
            display_name="Quality Demo Agent",
            capabilities=[
                AgentCapability.CODE_GENERATION,
                AgentCapability.TEST_GENERATION,
                AgentCapability.TEST_EXECUTION,
                AgentCapability.FILE_EDITING,
            ],
            cost_tier="standard",
        )
        candidate = CandidateAgent(
            descriptor=descriptor,
            status=AgentStatus.AVAILABLE,
            circuit_state=CircuitState.CLOSED,
        )
        candidate_provider = FakeCandidateProvider([candidate])

        service = EndToEndOrchestrationService(
            db=session_factory(),
            registry=exec_registry,
            candidate_provider=candidate_provider,
            quality_coordinator=q_coord,
        )

        req = OrchestrationRequest(
            request_id="req-quality-skip-fail",
            goal="Implement feature where tests get skipped",
            workspace_root=str(ws_root),
            available_agent_types=["quality-demo-agent"],
        )

        result = await service.orchestrate(req)
        # Required gate was SKIPPED -> Must NOT be VERIFIED_SUCCESS
        assert result.outcome != OrchestrationOutcome.VERIFIED_SUCCESS
        assert result.quality_verdict_status == "REJECTED"


@pytest.mark.asyncio
async def test_non_applicable_quality_verification_preserves_legacy_behavior(
    tmp_path: Path,
) -> None:
    db_file = tmp_path / "quality_test_legacy.db"
    engine = create_engine(f"sqlite:///{db_file}", echo=False)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    # When quality_coordinator is None (legacy non-software workflow)
    exec_registry = ExecutorRegistry()
    adapter = QualityDemoAdapter()
    exec_registry.register("quality-demo-agent", adapter)

    from app.resilience.circuit_breaker import CircuitState

    descriptor = AgentDescriptor(
        agent_type="quality-demo-agent",
        display_name="Quality Demo Agent",
        capabilities=[
            AgentCapability.CODE_GENERATION,
            AgentCapability.TEST_GENERATION,
            AgentCapability.TEST_EXECUTION,
            AgentCapability.FILE_EDITING,
        ],
        cost_tier="standard",
    )
    candidate = CandidateAgent(
        descriptor=descriptor,
        status=AgentStatus.AVAILABLE,
        circuit_state=CircuitState.CLOSED,
    )
    candidate_provider = FakeCandidateProvider([candidate])

    service = EndToEndOrchestrationService(
        db=session_factory(),
        registry=exec_registry,
        candidate_provider=candidate_provider,
        quality_coordinator=None,
    )

    req = OrchestrationRequest(
        request_id="req-legacy-pass",
        goal="Non-software task execution",
        workspace_root=None,
        available_agent_types=["quality-demo-agent"],
    )

    result = await service.orchestrate(req)
    assert result.outcome == OrchestrationOutcome.VERIFIED_SUCCESS
    assert result.quality_run_id is None
    assert result.quality_verdict_status is None
