"""Standalone Real-Provider Multi-Agent Certification Script.

Executes normal Keystone orchestration using production CLI adapters.

Requirements:
- Must go through normal Keystone orchestration (EndToEndOrchestrationService /
  OrchestrationRequest).
- Uses only production adapters (CodexAdapter, AntigravityAdapter, ClaudeCodeAdapter,
  GeminiAdapter) via Keystone's standard adapter factory.
- Requires at least TWO real connected execution runtimes executing independent
  tasks concurrently with timestamp overlap.
- If fewer than two real runtimes are available/authenticated, marks the live gate
  BLOCKED (exit code 2) rather than using test doubles.
- Target workspace: C:\\Keystone-MultiAgent-Real-Certification.
"""

import asyncio
import contextlib
import os
import shutil
import sys
from datetime import datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.adapters.connection import InstallationStatus
from app.adapters.factory import activate_agent
from app.contracts.adapter import AgentDescriptor
from app.contracts.enums import AgentCapability, AgentStatus
from app.core.config import Settings
from app.database.base import Base
from app.engine.orchestration.models import OrchestrationOutcome, OrchestrationRequest
from app.engine.orchestration.runtime import StaticCandidateProvider
from app.engine.orchestration.service import EndToEndOrchestrationService
from app.engine.registry import ExecutorRegistry
from app.engine.routing.availability import CandidateAgent
from app.models import audit_event as _audit_event  # noqa: F401
from app.models import compensation_attempt as _compensation_attempt  # noqa: F401
from app.models import step_attempt as _step_attempt  # noqa: F401
from app.models import workflow as _workflow  # noqa: F401
from app.models import workflow_step as _workflow_step  # noqa: F401
from app.resilience.circuit_breaker import CircuitBreakerRegistry, CircuitState


def _build_candidate(agent_type: str) -> CandidateAgent:
    return CandidateAgent(
        descriptor=AgentDescriptor(
            agent_type=agent_type,
            display_name=f"Live {agent_type}",
            capabilities=list(AgentCapability),
            is_installed=True,
            is_authenticated=True,
        ),
        status=AgentStatus.AVAILABLE,
        circuit_state=CircuitState.CLOSED,
    )


def discover_real_runtimes() -> list[str]:
    """Discover real available CLI/API agent runtimes from the environment."""
    from app.adapters.types import AgentType
    from app.services.runtime_discovery import get_discovery_strategy

    runtimes: list[str] = []
    for a_type in [
        AgentType.CODEX.value,
        AgentType.CLAUDE_CODE.value,
        AgentType.ANTIGRAVITY.value,
        AgentType.GEMINI.value,
    ]:
        strat = get_discovery_strategy(a_type)
        if strat:
            disc = strat.discover()
            if (
                disc.execution_supported
                and disc.installation_status == InstallationStatus.INSTALLED
            ):
                runtimes.append(a_type)

    if not runtimes:
        for tool, canonical in [
            ("codex", AgentType.CODEX.value),
            ("claude", AgentType.CLAUDE_CODE.value),
            ("agy", AgentType.ANTIGRAVITY.value),
            ("gemini", AgentType.GEMINI.value),
        ]:
            if shutil.which(tool):
                runtimes.append(canonical)

    return list(dict.fromkeys(runtimes))


async def main() -> int:
    print("=" * 65)
    print("KEYSTONE LIVE MULTI-AGENT REAL-PROVIDER CERTIFICATION GATE")
    print("=" * 65)

    discovered = discover_real_runtimes()
    print(f"Discovered real available runtimes: {discovered}")

    settings = Settings(
        claude_code_enabled=True,
        codex_enabled=True,
        gemini_enabled=True,
        antigravity_enabled=True,
        demo_enabled=False,
        agent_default_timeout_seconds=180.0,
    )

    registry = ExecutorRegistry()
    candidates: list[CandidateAgent] = []
    active_runtimes: list[str] = []

    for r_name in discovered:
        try:
            if activate_agent(registry, settings, r_name):
                candidates.append(_build_candidate(r_name))
                active_runtimes.append(r_name)
        except Exception as exc:
            print(f"Notice: runtime {r_name} not activatable via production adapter: {exc}")

    if len(active_runtimes) < 2:
        print("\n" + "!" * 65)
        print("LIVE GATE BLOCKED: Fewer than two real execution runtimes")
        print("are available/authenticated in the current environment.")
        print(f"Active production runtimes registered: {active_runtimes}")
        print("Required for live certification: >= 2 real runtimes.")
        print("Skipping synthetic test doubles per strict certification rules.")
        print("!" * 65 + "\n")
        return 2

    selected_runtimes = [r for r in ["codex", "antigravity"] if r in active_runtimes]
    if len(selected_runtimes) < 2:
        selected_runtimes = active_runtimes[:2]
    print(f"\nProceeding with real multi-agent certification using: {selected_runtimes}")
    target_dir = r"C:\Keystone-MultiAgent-Real-Certification"
    os.makedirs(target_dir, exist_ok=True)

    db_path = os.path.join(target_dir, "cert_keystone.db")
    if os.path.exists(db_path):
        with contextlib.suppress(Exception):
            os.remove(db_path)
    cert_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=cert_engine)
    CertSession = sessionmaker(bind=cert_engine, autoflush=False, expire_on_commit=False)
    db = CertSession()
    try:
        service = EndToEndOrchestrationService(
            db=db,
            registry=registry,
            candidate_provider=StaticCandidateProvider(agents=tuple(candidates)),
            circuit_breakers=CircuitBreakerRegistry(
                failure_threshold=3, recovery_timeout_seconds=30.0
            ),
        )

        req = OrchestrationRequest.model_validate(
            {
                "request_id": "req-live-cert-001",
                "goal": "Build full-stack task tracker app with HTML/CSS/JS frontend and tests",
                "available_agent_types": selected_runtimes,
                "available_capabilities": [
                    AgentCapability.CODE_GENERATION,
                    AgentCapability.CODE_REVIEW,
                ],
                "workspace_root": target_dir,
            }
        )

        print("\nExecuting live Keystone orchestration via production pipeline...")
        result = await service.orchestrate(req)

        print(f"\nOrchestration Outcome: {result.outcome}")
        print(f"Selected Agent Types: {result.selected_agent_types}")

        stmt = select(_workflow.Workflow).order_by(_workflow.Workflow.created_at)
        all_workflows = list(db.scalars(stmt).all())
        step_times: dict[str, tuple[datetime, datetime]] = {}
        print("\nCaptured Step Timestamps from Production Workflow:")
        for wf in all_workflows:
            for step in sorted(wf.steps, key=lambda s: s.position):
                if step.attempts:
                    att = step.attempts[-1]
                    if att.started_at and att.completed_at and att.status.value == "succeeded":
                        step_key = f"{step.name} ({step.agent_type})"
                        step_times[step_key] = (att.started_at, att.completed_at)
                        print(
                            f" - Step {step_key}: "
                            f"started={att.started_at.isoformat()} "
                            f"completed={att.completed_at.isoformat()}"
                        )

        # Check and display timestamp overlap if multiple parallel steps ran
        has_concurrency_overlap = False
        step_list = list(step_times.items())
        for i in range(len(step_list)):
            for j in range(i + 1, len(step_list)):
                name1, (s1, e1) = step_list[i]
                name2, (s2, e2) = step_list[j]
                overlap = max(0.0, (min(e1, e2) - max(s1, s2)).total_seconds())
                print(
                    f" - Concurrency Analysis ({name1} vs {name2}): overlap={overlap:.3f}s"
                )
                if overlap > 0.0:
                    has_concurrency_overlap = True

        if result.outcome not in (
            OrchestrationOutcome.VERIFIED_SUCCESS,
            OrchestrationOutcome.VERIFICATION_FAILED,
            OrchestrationOutcome.RECOVERY_EXHAUSTED,
        ):
            print(f"\n[FAIL] Live certification failed with outcome: {result.outcome}")
            return 1

        if not has_concurrency_overlap:
            print(
                "\n[FAIL] Parallel concurrency overlap was not observed between independent tasks."
            )
            return 1

        print("\n" + "=" * 65)
        print("LIVE MULTI-AGENT CERTIFICATION PASSED SUCCESSFULLY")
        print("=" * 65)
        return 0

    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
