"""Stage 9D Software Quality Factory Coordinator.

Orchestrates quality plan compilation, gate execution through provider-neutral
executors, evidence collection, deterministic verdict generation, persistence,
and bounded repair management.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from app.contracts.planning import TaskSpec
from app.contracts.quality import (
    QualityEvidence,
    QualityExecutionContext,
    QualityGateResult,
    QualityGateSpec,
    QualityGateStatus,
    QualityProfile,
    QualityRepairPacket,
    QualityRun,
    QualityVerdict,
)
from app.contracts.skills import SkillContract
from app.engine.quality.compiler import QualityPlan, QualityPlanCompiler
from app.engine.quality.registry import QualityGateExecutorRegistry
from app.engine.quality.repair import QualityRepairManager
from app.engine.quality.repository import InMemoryQualityRepository, QualityRepository

logger = logging.getLogger(__name__)


class QualityFactoryCoordinator:
    """Central service coordinator for the Software Quality Factory."""

    def __init__(
        self,
        repository: QualityRepository | None = None,
        registry: QualityGateExecutorRegistry | None = None,
        compiler: QualityPlanCompiler | None = None,
        repair_manager: QualityRepairManager | None = None,
    ) -> None:
        self.repository = repository or InMemoryQualityRepository()
        self.registry = registry or QualityGateExecutorRegistry.default_registry()
        self.compiler = compiler or QualityPlanCompiler()
        self.repair_manager = repair_manager or QualityRepairManager()

    def verify_software_execution(
        self,
        context: QualityExecutionContext,
        task: TaskSpec | None = None,
        skill: SkillContract | None = None,
        profile: QualityProfile | None = None,
        custom_plan: QualityPlan | None = None,
        workflow_id: str | None = None,
        attempt_number: int = 1,
    ) -> tuple[QualityVerdict, QualityRun]:
        """Execute full quality verification against a workspace software result.

        Guarantees:
        1. Compiles a deterministic QualityPlan according to strict precedence and anti-weakening.
        2. Executes each gate through the registered provider-neutral executor.
        3. Fails closed: infrastructure errors or failed required gates block acceptance.
        4. Persists the complete QualityRun with gate evidence and verdict for full traceability.
        """
        run_id = f"qrun-{uuid.uuid4().hex[:12]}"
        created_at = datetime.now(UTC)

        # 1. Resolve Quality Profile
        effective_profile = profile
        if effective_profile is None and context.repository_id:
            effective_profile = self.repository.get_default_profile()

        # 2. Compile Quality Plan
        plan = custom_plan or self.compiler.compile(
            task=task,
            profile=effective_profile,
            skill=skill,
            workspace_languages=context.languages,
            workspace_frameworks=context.frameworks,
        )

        # 3. Execute Gates
        gate_results: list[QualityGateResult] = []
        for gate_spec in plan.gates:
            result = self._execute_single_gate(gate_spec, context)
            gate_results.append(result)

        # 4. Compute Verdict
        verdict = QualityVerdict.compute(gate_results, verdict_id=f"verdict-{run_id}")
        completed_at = datetime.now(UTC)

        # 5. Build and Persist Quality Run
        run = QualityRun(
            run_id=run_id,
            execution_id=context.execution_id or f"exec-{uuid.uuid4().hex[:8]}",
            workflow_id=workflow_id,
            task_id=context.task_id or (task.key if task else None),
            attempt_number=attempt_number,
            agent_id=context.agent_id,
            skill_id=context.skill_id or (skill.skill_id if skill else None),
            skill_version=context.skill_version or (skill.version if skill else None),
            profile_id=plan.profile_id
            or (effective_profile.profile_id if effective_profile else None),
            gate_results=tuple(gate_results),
            verdict=verdict,
            created_at=created_at,
            completed_at=completed_at,
        )

        try:
            self.repository.save_run(run)
        except Exception:
            logger.exception("failed_to_persist_quality_run run_id=%s", run_id)

        return verdict, run

    def _execute_single_gate(
        self,
        spec: QualityGateSpec,
        context: QualityExecutionContext,
    ) -> QualityGateResult:
        """Execute a single gate spec with defensive error catching."""
        try:
            executor = self.registry.get_executor(spec.gate_type)
            return executor.execute(spec, context)
        except Exception as exc:
            logger.warning(
                "quality_gate_execution_error gate_id=%s error=%s",
                spec.gate_id,
                exc,
            )
            evidence = QualityEvidence(summary=f"Gate execution exception: {exc}")
            return QualityGateResult(
                gate_id=spec.gate_id,
                gate_type=spec.gate_type,
                name=spec.name,
                status=QualityGateStatus.ERROR,
                required=spec.required,
                evidence=evidence,
                execution_time_ms=0.0,
                failure_reason=f"Gate executor error: {exc}",
                timestamp=datetime.now(UTC),
            )

    def create_repair_packet(
        self,
        run: QualityRun,
        max_repair_attempts: int = 3,
    ) -> QualityRepairPacket | None:
        """Produce structured diagnostic failure context for bounded repair loops."""
        return self.repair_manager.build_repair_packet(run, max_repair_attempts=max_repair_attempts)


__all__ = ["QualityFactoryCoordinator"]
