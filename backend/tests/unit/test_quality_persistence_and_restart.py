"""Unit tests for Quality Repository persistence, queries, and restart integrity."""

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.contracts.quality import (
    QualityEvidence,
    QualityGateResult,
    QualityGateSpec,
    QualityGateStatus,
    QualityGateType,
    QualityProfile,
    QualityRun,
    QualityVerdict,
)
from app.database.base import Base
from app.engine.quality.repository import InMemoryQualityRepository, SqlAlchemyQualityRepository


def test_in_memory_quality_repository() -> None:
    repo = InMemoryQualityRepository()

    # Profile CRUD & Default switching
    p1 = QualityProfile(profile_id="p1", name="Profile 1", is_default=True)
    repo.save_profile(p1)
    assert repo.get_default_profile().profile_id == "p1"

    p2 = QualityProfile(profile_id="p2", name="Profile 2", is_default=True)
    repo.save_profile(p2)
    assert repo.get_default_profile().profile_id == "p2"
    assert repo.get_profile("p1").is_default is False

    # Run saving & queries
    r1 = QualityGateResult(
        gate_id="g1",
        gate_type=QualityGateType.TEST,
        name="Unit Tests",
        status=QualityGateStatus.PASSED,
        required=True,
        evidence=QualityEvidence(summary="Passed"),
    )
    verdict = QualityVerdict.compute([r1], verdict_id="v1")
    now = datetime.now(UTC)
    run1 = QualityRun(
        run_id="run-1",
        execution_id="exec-100",
        workflow_id="wf-100",
        task_id="task-1",
        attempt_number=1,
        gate_results=(r1,),
        verdict=verdict,
        created_at=now,
        completed_at=now,
    )
    repo.save_run(run1)

    assert repo.get_run("run-1") is not None
    assert len(repo.get_runs_by_execution("exec-100")) == 1
    assert len(repo.get_runs_by_task("task-1")) == 1
    assert len(repo.get_runs_by_workflow("wf-100")) == 1
    assert repo.get_latest_run_for_task("task-1").run_id == "run-1"


def test_sqlalchemy_quality_repository_and_restart() -> None:
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    repo = SqlAlchemyQualityRepository(session_factory=session_factory)

    # 1. Save Profile
    g1 = QualityGateSpec(
        gate_id="test-gate",
        gate_type=QualityGateType.TEST,
        name="DB Test Gate",
        required=True,
        timeout_seconds=40.0,
    )
    prof = QualityProfile(
        profile_id="sql-prof-1",
        name="SQL Profile",
        target_languages=("python",),
        gates=(g1,),
        is_default=True,
    )
    repo.save_profile(prof)

    # 2. Save QualityRun with Gate Results
    gr1 = QualityGateResult(
        gate_id="test-gate",
        gate_type=QualityGateType.TEST,
        name="DB Test Gate",
        status=QualityGateStatus.PASSED,
        required=True,
        evidence=QualityEvidence(
            summary="All 10 tests passed",
            exit_code=0,
            diagnostics=("test_1 OK", "test_2 OK"),
            metrics={"passed": 10},
        ),
        execution_time_ms=125.0,
    )
    v = QualityVerdict.compute([gr1], verdict_id="verdict-sql-1")
    now = datetime.now(UTC)
    qrun = QualityRun(
        run_id="qrun-sql-1",
        execution_id="exec-sql-1",
        workflow_id="wf-sql-1",
        task_id="task-sql-1",
        attempt_number=1,
        agent_id="agent-coder",
        skill_id="py-skill",
        skill_version="1.0.0",
        profile_id="sql-prof-1",
        gate_results=(gr1,),
        verdict=v,
        created_at=now,
        completed_at=now,
    )
    repo.save_run(qrun)

    # 3. Simulate process restart by creating a new repository instance pointing to the same DB
    restarted_repo = SqlAlchemyQualityRepository(session_factory=session_factory)

    loaded_prof = restarted_repo.get_profile("sql-prof-1")
    assert loaded_prof is not None
    assert loaded_prof.name == "SQL Profile"
    assert len(loaded_prof.gates) == 1
    assert loaded_prof.gates[0].gate_id == "test-gate"
    assert loaded_prof.is_default is True

    loaded_run = restarted_repo.get_run("qrun-sql-1")
    assert loaded_run is not None
    assert loaded_run.execution_id == "exec-sql-1"
    assert loaded_run.verdict is not None
    assert loaded_run.verdict.passed is True
    assert len(loaded_run.gate_results) == 1
    assert loaded_run.gate_results[0].gate_id == "test-gate"
    assert loaded_run.gate_results[0].evidence is not None
    assert loaded_run.gate_results[0].evidence.summary == "All 10 tests passed"
    assert loaded_run.gate_results[0].evidence.metrics["passed"] == 10


def test_re_persistence_reconciles_gate_rows_atomically() -> None:
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    repo = SqlAlchemyQualityRepository(session_factory=session_factory)

    now = datetime.now(UTC)
    g1 = QualityGateResult(
        gate_id="g1",
        gate_type=QualityGateType.TEST,
        name="Test 1",
        status=QualityGateStatus.PASSED,
        required=True,
        evidence=QualityEvidence(summary="g1 pass"),
    )
    g2 = QualityGateResult(
        gate_id="g2",
        gate_type=QualityGateType.LINT,
        name="Test 2",
        status=QualityGateStatus.PASSED,
        required=True,
        evidence=QualityEvidence(summary="g2 pass"),
    )
    run_v1 = QualityRun(
        run_id="run-reconcile",
        execution_id="exec-rec",
        task_id="task-rec",
        attempt_number=1,
        gate_results=(g1, g2),
        verdict=QualityVerdict.compute([g1, g2], verdict_id="v-1"),
        created_at=now,
    )
    repo.save_run(run_v1)
    assert len(repo.get_gate_results_for_run("run-reconcile")) == 2

    # Re-save the same run with ONLY g1 (updated) and g2 removed
    g1_updated = QualityGateResult(
        gate_id="g1",
        gate_type=QualityGateType.TEST,
        name="Test 1 Updated",
        status=QualityGateStatus.PASSED,
        required=True,
        evidence=QualityEvidence(summary="g1 updated pass"),
    )
    run_v2 = QualityRun(
        run_id="run-reconcile",
        execution_id="exec-rec",
        task_id="task-rec",
        attempt_number=1,
        gate_results=(g1_updated,),
        verdict=QualityVerdict.compute([g1_updated], verdict_id="v-2"),
        created_at=now,
    )
    repo.save_run(run_v2)

    # Gate results MUST be reconciled to exactly 1 gate (no stale g2 row lingering)
    gate_results = repo.get_gate_results_for_run("run-reconcile")
    assert len(gate_results) == 1
    assert gate_results[0].gate_id == "g1"
    assert gate_results[0].name == "Test 1 Updated"


def test_subsequent_repair_attempt_preserves_earlier_failed_run() -> None:
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    repo = SqlAlchemyQualityRepository(session_factory=session_factory)

    now = datetime.now(UTC)
    # Attempt 1: Failed
    g_fail = QualityGateResult(
        gate_id="g-test",
        gate_type=QualityGateType.TEST,
        name="Test Gate",
        status=QualityGateStatus.FAILED,
        required=True,
        evidence=QualityEvidence(summary="AssertionError"),
        failure_reason="AssertionError",
    )
    run_att1 = QualityRun(
        run_id="run-att-1",
        execution_id="exec-repair-trace",
        task_id="task-code",
        attempt_number=1,
        gate_results=(g_fail,),
        verdict=QualityVerdict.compute([g_fail], verdict_id="v-att1"),
        created_at=now,
    )
    repo.save_run(run_att1)

    # Attempt 2: Repaired & Passed
    g_pass = QualityGateResult(
        gate_id="g-test",
        gate_type=QualityGateType.TEST,
        name="Test Gate",
        status=QualityGateStatus.PASSED,
        required=True,
        evidence=QualityEvidence(summary="All tests passed"),
    )
    run_att2 = QualityRun(
        run_id="run-att-2",
        execution_id="exec-repair-trace",
        task_id="task-code",
        attempt_number=2,
        gate_results=(g_pass,),
        verdict=QualityVerdict.compute([g_pass], verdict_id="v-att2"),
        created_at=now,
    )
    repo.save_run(run_att2)

    # Verify both attempts exist independently with full immutable historical accuracy
    runs = repo.get_runs_by_execution("exec-repair-trace")
    assert len(runs) == 2

    r1 = next(r for r in runs if r.attempt_number == 1)
    assert r1.verdict is not None and r1.verdict.passed is False
    assert len(r1.gate_results) == 1 and r1.gate_results[0].status == QualityGateStatus.FAILED

    r2 = next(r for r in runs if r.attempt_number == 2)
    assert r2.verdict is not None and r2.verdict.passed is True
    assert len(r2.gate_results) == 1 and r2.gate_results[0].status == QualityGateStatus.PASSED

    latest = repo.get_latest_run_for_task("task-code", execution_id="exec-repair-trace")
    assert latest is not None
    assert latest.attempt_number == 2
    assert latest.verdict is not None and latest.verdict.passed is True
