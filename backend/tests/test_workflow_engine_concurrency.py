"""Deterministic Concurrency Unit Tests for WorkflowEngine.execute_workflow_async."""

import time
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.contracts.adapter import AgentDescriptor
from app.contracts.enums import AgentCapability
from app.engine.executor import AgentExecutor, StepExecutionRequest
from app.engine.registry import ExecutorRegistry
from app.engine.workflow_engine import WorkflowEngine
from app.models.enums import WorkflowStatus
from app.schemas.workflow import WorkflowCreate, WorkflowStepCreate
from app.services import workflow_service


class SleepyExecutor(AgentExecutor):
    """Executor that sleeps briefly to simulate non-instant work."""

    def __init__(self, agent_type: str, sleep_seconds: float = 0.2) -> None:
        self._agent_type = agent_type
        self._sleep_seconds = sleep_seconds

    @property
    def descriptor(self) -> AgentDescriptor:
        return AgentDescriptor(
            agent_type=self._agent_type,
            display_name=f"Sleepy {self._agent_type}",
            capabilities=[AgentCapability.CODE_GENERATION, AgentCapability.FILE_EDITING],
        )

    def execute(self, request: StepExecutionRequest) -> dict[str, Any]:
        time.sleep(self._sleep_seconds)
        return {"status": "ok", "task_id": request.step_id}


@pytest.mark.asyncio
async def test_workflow_engine_real_concurrency_timestamp_overlap(db_session: Session) -> None:
    """Prove actual timestamp overlap between two independent parallel-safe tasks."""
    registry = ExecutorRegistry()
    registry.register("codex", SleepyExecutor("codex", sleep_seconds=0.3))
    registry.register("antigravity", SleepyExecutor("antigravity", sleep_seconds=0.3))

    step1 = WorkflowStepCreate(
        name="T1 Frontend",
        position=0,
        agent_type="codex",
        input_payload={
            "task_key": "T1",
            "depends_on": [],
            "target_files": ["index.html"],
            "target_files_ownership": "KNOWN",
            "parallel_safe": True,
        },
    )
    step2 = WorkflowStepCreate(
        name="T2 Backend",
        position=1,
        agent_type="antigravity",
        input_payload={
            "task_key": "T2",
            "depends_on": [],
            "target_files": ["server.py"],
            "target_files_ownership": "KNOWN",
            "parallel_safe": True,
        },
    )

    create_req = WorkflowCreate(
        name="Concurrent Test",
        description="Parallel test",
        steps=[step1, step2],
    )
    workflow = workflow_service.create_workflow(db_session, create_req)

    engine = WorkflowEngine(db_session, registry)
    executed, timestamps = await engine.execute_workflow_async(workflow.id, max_concurrency=3)

    assert WorkflowStatus(executed.status) == WorkflowStatus.SUCCEEDED
    assert len(timestamps) == 2

    steps_by_pos = sorted(executed.steps, key=lambda s: s.position)
    s1_id, s2_id = steps_by_pos[0].id, steps_by_pos[1].id

    s1_start = timestamps[s1_id]["start"]
    s1_end = timestamps[s1_id]["end"]
    s2_start = timestamps[s2_id]["start"]
    s2_end = timestamps[s2_id]["end"]

    # Prove actual timestamp overlap: A.start < B.end AND B.start < A.end
    assert s1_start < s2_end, f"Expected s1_start ({s1_start}) < s2_end ({s2_end})"
    assert s2_start < s1_end, f"Expected s2_start ({s2_start}) < s1_end ({s1_end})"


@pytest.mark.asyncio
async def test_workflow_engine_strict_serialization_for_conflicting_tasks(
    db_session: Session,
) -> None:
    """Prove strictly that two conflicting tasks NEVER overlap in time."""
    registry = ExecutorRegistry()
    registry.register("codex", SleepyExecutor("codex", sleep_seconds=0.2))
    registry.register("antigravity", SleepyExecutor("antigravity", sleep_seconds=0.2))

    # T1 and T2 both target 'shared.js' -> strict conflict
    step1 = WorkflowStepCreate(
        name="T1",
        position=0,
        agent_type="codex",
        input_payload={
            "task_key": "T1",
            "depends_on": [],
            "target_files": ["shared.js"],
            "target_files_ownership": "KNOWN",
            "parallel_safe": True,
        },
    )
    step2 = WorkflowStepCreate(
        name="T2",
        position=1,
        agent_type="antigravity",
        input_payload={
            "task_key": "T2",
            "depends_on": [],
            "target_files": ["shared.js"],
            "target_files_ownership": "KNOWN",
            "parallel_safe": True,
        },
    )

    create_req = WorkflowCreate(
        name="Conflict Serialized Test",
        description="Serial overlap test",
        steps=[step1, step2],
    )
    workflow = workflow_service.create_workflow(db_session, create_req)

    engine = WorkflowEngine(db_session, registry)
    executed, timestamps = await engine.execute_workflow_async(workflow.id, max_concurrency=3)

    assert WorkflowStatus(executed.status) == WorkflowStatus.SUCCEEDED
    steps_by_pos = sorted(executed.steps, key=lambda s: s.position)
    s1_id, s2_id = steps_by_pos[0].id, steps_by_pos[1].id

    s1_start = timestamps[s1_id]["start"]
    s1_end = timestamps[s1_id]["end"]
    s2_start = timestamps[s2_id]["start"]
    s2_end = timestamps[s2_id]["end"]

    # Strict serialization check: task2.start >= task1.end OR task1.start >= task2.end
    no_overlap = (s2_start >= s1_end) or (s1_start >= s2_end)
    msg = (
        "Conflicting tasks must not overlap: "
        f"S1[{s1_start} - {s1_end}] vs S2[{s2_start} - {s2_end}]"
    )
    assert no_overlap, msg


@pytest.mark.asyncio
async def test_workflow_engine_unknown_ownership_serializes(db_session: Session) -> None:
    """Prove that Unknown file ownership conservatively serializes tasks."""
    registry = ExecutorRegistry()
    registry.register("codex", SleepyExecutor("codex", sleep_seconds=0.2))
    registry.register("antigravity", SleepyExecutor("antigravity", sleep_seconds=0.2))

    step1 = WorkflowStepCreate(
        name="T1",
        position=0,
        agent_type="codex",
        input_payload={
            "task_key": "T1",
            "depends_on": [],
            "target_files": [],
            "target_files_ownership": "UNKNOWN",
            "parallel_safe": False,
        },
    )
    step2 = WorkflowStepCreate(
        name="T2",
        position=1,
        agent_type="antigravity",
        input_payload={
            "task_key": "T2",
            "depends_on": [],
            "target_files": ["server.py"],
            "target_files_ownership": "KNOWN",
            "parallel_safe": True,
        },
    )

    create_req = WorkflowCreate(
        name="Unknown Serialization Test",
        description="Unknown serial test",
        steps=[step1, step2],
    )
    workflow = workflow_service.create_workflow(db_session, create_req)

    engine = WorkflowEngine(db_session, registry)
    executed, timestamps = await engine.execute_workflow_async(workflow.id, max_concurrency=3)

    assert WorkflowStatus(executed.status) == WorkflowStatus.SUCCEEDED
    steps_by_pos = sorted(executed.steps, key=lambda s: s.position)
    s1_id, s2_id = steps_by_pos[0].id, steps_by_pos[1].id

    s1_start = timestamps[s1_id]["start"]
    s1_end = timestamps[s1_id]["end"]
    s2_start = timestamps[s2_id]["start"]
    s2_end = timestamps[s2_id]["end"]

    # Unknown must not overlap
    no_overlap = (s2_start >= s1_end) or (s1_start >= s2_end)
    assert no_overlap, "Tasks must not overlap when one has UNKNOWN files"


@pytest.mark.asyncio
async def test_workflow_engine_fails_safely_when_worker_session_creation_fails(
    db_session: Session,
) -> None:
    """Prove that if worker session factory fails, worker fails safely and NEVER
    silently reuses the shared parent SQLAlchemy session."""
    registry = ExecutorRegistry()
    registry.register("codex", SleepyExecutor("codex", sleep_seconds=0.1))

    step1 = WorkflowStepCreate(
        name="T1",
        position=0,
        agent_type="codex",
        input_payload={"task_key": "T1", "depends_on": [], "target_files": ["a.py"]},
    )
    create_req = WorkflowCreate(
        name="Session Failure Safety Test",
        description="Safe failure test",
        steps=[step1],
    )
    workflow = workflow_service.create_workflow(db_session, create_req)

    mock_db = MagicMock(spec=db_session)
    mock_db.get_bind.side_effect = RuntimeError("Cannot bind engine for worker")
    mock_eng = WorkflowEngine(mock_db, registry)

    with pytest.raises(RuntimeError) as exc:
        mock_eng._execute_step(workflow, workflow.steps[0], MagicMock())

    assert "Failed to create independent database session for worker step" in str(exc.value)
