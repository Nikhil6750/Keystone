"""Stage 9E: real production-path wiring and failure isolation.

Proves two things through the actual `EndToEndOrchestrationService.orchestrate()`
entry point (not by directly instantiating intelligence classes in isolation):

1. A completed real orchestration projects genuine graph evidence -- nodes,
   edges, and (when applicable) a Stage 9D-integrated quality run -- reachable
   through the query service.
2. A broken intelligence-graph persistence layer never affects the
   authoritative orchestration/quality outcome (failure isolation, see
   `app.engine.intelligence.builder`'s module docstring).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.contracts.adapter import AgentDescriptor
from app.contracts.enums import AgentCapability, AgentStatus
from app.contracts.intelligence import IntelligenceNodeType
from app.contracts.quality import (
    QualityGateSpec,
    QualityGateStatus,
    QualityGateType,
    QualityProfile,
)
from app.database.base import Base
from app.engine.intelligence.builder import EngineeringIntelligenceGraphBuilder
from app.engine.intelligence.graph_repository import (
    InMemoryIntelligenceGraphRepository,
    SqlAlchemyIntelligenceGraphRepository,
)
from app.engine.intelligence.query_service import EngineeringIntelligenceQueryService
from app.engine.orchestration.models import OrchestrationOutcome, OrchestrationRequest
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


class IntelligenceDemoAdapter:
    def __init__(self) -> None:
        self.attempts = 0

    def execute(self, request: Any) -> dict[str, Any]:
        self.attempts += 1
        return {
            "agent_type": "intelligence-demo-agent",
            "content": f"execution attempt {self.attempts} output",
            "exit_code": 0,
            "output": "5 passed in 0.05s",
            "tests_total": 5,
            "tests_passed": 5,
            "tests_failed": 0,
            "tests_skipped": 0,
            "structured_evidence": {"output_file": "src/app.py", "attempt": self.attempts},
            "metadata": {"execution_mode": "demo", "exit_code": 0},
        }


def _candidate_provider() -> FakeCandidateProvider:
    descriptor = AgentDescriptor(
        agent_type="intelligence-demo-agent",
        display_name="Intelligence Demo Agent",
        capabilities=[
            AgentCapability.CODE_GENERATION,
            AgentCapability.TEST_GENERATION,
            AgentCapability.TEST_EXECUTION,
            AgentCapability.FILE_EDITING,
        ],
        cost_tier="standard",
    )
    candidate = CandidateAgent(
        descriptor=descriptor, status=AgentStatus.AVAILABLE, circuit_state=CircuitState.CLOSED
    )
    return FakeCandidateProvider([candidate])


@pytest.mark.asyncio
async def test_real_orchestration_projects_intelligence_graph_evidence(tmp_path: Path) -> None:
    db_file = tmp_path / "intel_prod.db"
    engine = create_engine(f"sqlite:///{db_file}", echo=False)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    q_repo = SqlAlchemyQualityRepository(session_factory=session_factory)
    q_registry = QualityGateExecutorRegistry()
    mock_exec = MockQualityGateExecutor(default_status=QualityGateStatus.PASSED)
    q_registry.register_executor(QualityGateType.TEST, mock_exec)
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

    graph_repo = SqlAlchemyIntelligenceGraphRepository(session_factory=session_factory)
    intelligence_builder = EngineeringIntelligenceGraphBuilder(
        graph_repo, session_factory, quality_repository=q_repo
    )
    query = EngineeringIntelligenceQueryService(graph_repo)

    with tempfile.TemporaryDirectory() as ws_dir:
        exec_registry = ExecutorRegistry()
        adapter = IntelligenceDemoAdapter()
        exec_registry.register("intelligence-demo-agent", adapter)

        service = EndToEndOrchestrationService(
            db=session_factory(),
            registry=exec_registry,
            candidate_provider=_candidate_provider(),
            quality_coordinator=q_coord,
            intelligence_builder=intelligence_builder,
        )

        req = OrchestrationRequest(
            request_id="req-intel-prod-1",
            goal="Implement feature with verified tests",
            workspace_root=ws_dir,
            available_agent_types=["intelligence-demo-agent"],
        )

        result = await service.orchestrate(req)
        assert result.outcome == OrchestrationOutcome.VERIFIED_SUCCESS
        assert result.workflow_id is not None

    # Real production evidence reachable through the query service --
    # never constructed by directly instantiating graph classes in isolation.
    workflow_nodes = graph_repo.get_nodes_by_type(
        IntelligenceNodeType.WORKFLOW, workflow_id=result.workflow_id
    )
    assert len(workflow_nodes) == 1

    attempts = graph_repo.get_nodes_by_type(
        IntelligenceNodeType.ATTEMPT, workflow_id=result.workflow_id
    )
    assert len(attempts) >= 1
    assert all(a.status == "succeeded" for a in attempts)

    # One Stage 9D quality run per executed task -- exact correlation via
    # the real `step_to_task` mapping, not the best-effort rebuild fallback
    # (see `EngineeringIntelligenceGraphBuilder.ingest_workflow`), so every
    # attempt gets its own linked run even though every task in this test
    # shares the same agent and attempt_number.
    quality_runs = graph_repo.get_nodes_by_type(
        IntelligenceNodeType.QUALITY_RUN, workflow_id=result.workflow_id
    )
    assert len(quality_runs) == len(attempts)
    assert all(r.metadata.get("passed") is True for r in quality_runs)

    agent_reliability = query.get_agent_reliability("intelligence-demo-agent")
    assert agent_reliability.observed_executions == len(attempts)
    assert agent_reliability.quality_verified_successes == len(attempts)


@pytest.mark.asyncio
async def test_intelligence_projection_failure_does_not_affect_orchestration_result(
    tmp_path: Path,
) -> None:
    """A completely broken intelligence graph repository must never turn a
    real, successful orchestration into a failure -- intelligence
    projection is downstream analytical state, never authoritative."""

    class ExplodingGraphRepository(InMemoryIntelligenceGraphRepository):
        def upsert_node(self, node: Any) -> bool:
            raise RuntimeError("simulated intelligence graph persistence outage")

    db_file = tmp_path / "intel_failure_isolation.db"
    engine = create_engine(f"sqlite:///{db_file}", echo=False)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    broken_builder = EngineeringIntelligenceGraphBuilder(
        ExplodingGraphRepository(), session_factory
    )

    with tempfile.TemporaryDirectory() as ws_dir:
        exec_registry = ExecutorRegistry()
        adapter = IntelligenceDemoAdapter()
        exec_registry.register("intelligence-demo-agent", adapter)

        service = EndToEndOrchestrationService(
            db=session_factory(),
            registry=exec_registry,
            candidate_provider=_candidate_provider(),
            intelligence_builder=broken_builder,
        )

        req = OrchestrationRequest(
            request_id="req-intel-failure-isolation",
            goal="Implement feature despite broken intelligence graph",
            workspace_root=ws_dir,
            available_agent_types=["intelligence-demo-agent"],
        )

        # Must not raise, and must still report the real, authoritative outcome.
        result = await service.orchestrate(req)
        assert result.outcome == OrchestrationOutcome.VERIFIED_SUCCESS
        assert result.workflow_id is not None

    # The authoritative workflow itself was persisted normally.
    with session_factory() as session:
        from app.models.workflow import Workflow

        wf = session.get(Workflow, result.workflow_id)
        assert wf is not None
        assert wf.status.value == "succeeded"
