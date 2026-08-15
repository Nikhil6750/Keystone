"""Unit tests for Stage 9D Software Quality Factory Domain Contracts."""

from datetime import UTC, datetime

import pytest

from app.contracts.quality import (
    QualityContractValidationError,
    QualityEvidence,
    QualityGateResult,
    QualityGateSpec,
    QualityGateStatus,
    QualityGateType,
    QualityProfile,
    QualityRepairPacket,
    QualityVerdict,
    QualityVerdictStatus,
)


def test_quality_gate_spec_validation() -> None:
    # Valid spec
    spec = QualityGateSpec(
        gate_id="test-gate-1",
        gate_type=QualityGateType.TEST,
        name="Unit Tests",
        required=True,
        timeout_seconds=45.0,
    )
    assert spec.gate_id == "test-gate-1"
    assert spec.required is True
    assert spec.timeout_seconds == 45.0

    # Blank gate_id rejected
    with pytest.raises(QualityContractValidationError, match="gate_id must not be blank"):
        QualityGateSpec(gate_id="", gate_type=QualityGateType.TEST, name="Blank ID")

    # Shell injection characters rejected in gate_id
    with pytest.raises(QualityContractValidationError, match="disallowed shell characters"):
        QualityGateSpec(gate_id="gate; rm -rf /", gate_type=QualityGateType.TEST, name="Injected")

    # Non-positive timeout rejected
    with pytest.raises(QualityContractValidationError, match="timeout_seconds must be between"):
        QualityGateSpec(
            gate_id="gate-2",
            gate_type=QualityGateType.TEST,
            name="Bad Timeout",
            timeout_seconds=0.0,
        )


def test_quality_evidence_validation() -> None:
    # Valid evidence
    ev = QualityEvidence(
        summary="All tests passed",
        exit_code=0,
        diagnostics=("test_foo passed",),
        artifact_references=("src/app.py",),
        stdout="OK",
        metrics={"passed": 5},
    )
    assert ev.exit_code == 0
    assert len(ev.diagnostics) == 1

    # Rejection of reasoning-shaped keys in metrics or metadata
    with pytest.raises(QualityContractValidationError, match="Unsafe evidence metrics"):
        QualityEvidence(
            summary="Bad metrics",
            metrics={"chain_of_thought": "secret thought"},
        )


def test_quality_gate_result_invariants() -> None:
    ev_passed = QualityEvidence(summary="Passed")
    ev_empty = QualityEvidence(summary="")

    # Passed result must not have failure_reason
    with pytest.raises(
        QualityContractValidationError,
        match="failure_reason must be None when gate status is PASSED",
    ):
        QualityGateResult(
            gate_id="gate-1",
            gate_type=QualityGateType.TEST,
            name="Test",
            status=QualityGateStatus.PASSED,
            required=True,
            evidence=ev_passed,
            failure_reason="Something failed",
        )

    # Failed result without evidence summary must have explicit failure_reason
    with pytest.raises(
        QualityContractValidationError,
        match="failure_reason is required when gate status is FAILED",
    ):
        QualityGateResult(
            gate_id="gate-1",
            gate_type=QualityGateType.TEST,
            name="Test",
            status=QualityGateStatus.FAILED,
            required=True,
            evidence=ev_empty,
            failure_reason=None,
        )


def test_quality_verdict_computation_aggregation() -> None:
    # 1. Zero gates -> Neutral Accepted
    v_empty = QualityVerdict.compute([], verdict_id="v-empty")
    assert v_empty.status == QualityVerdictStatus.ACCEPTED
    assert v_empty.passed is True
    assert v_empty.total_gates == 0

    # 2. All required gates passed
    r1 = QualityGateResult(
        gate_id="g1",
        gate_type=QualityGateType.TEST,
        name="Unit Tests",
        status=QualityGateStatus.PASSED,
        required=True,
        evidence=QualityEvidence(summary="Passed"),
    )
    r2 = QualityGateResult(
        gate_id="g2",
        gate_type=QualityGateType.LINT,
        name="Linter",
        status=QualityGateStatus.PASSED,
        required=True,
        evidence=QualityEvidence(summary="Passed"),
    )
    v_pass = QualityVerdict.compute([r1, r2], verdict_id="v-pass")
    assert v_pass.status == QualityVerdictStatus.ACCEPTED
    assert v_pass.passed is True
    assert v_pass.passed_gates == 2
    assert v_pass.failed_gates == 0

    # 3. Advisory (required=False) gate failed does NOT reject verdict
    r_advisory = QualityGateResult(
        gate_id="g3",
        gate_type=QualityGateType.TYPE_CHECK,
        name="MyPy Check",
        status=QualityGateStatus.FAILED,
        required=False,
        evidence=QualityEvidence(summary="Advisory type failure"),
        failure_reason="Advisory type error",
    )
    v_advisory = QualityVerdict.compute([r1, r_advisory], verdict_id="v-adv")
    assert v_advisory.status == QualityVerdictStatus.ACCEPTED
    assert v_advisory.passed is True
    assert v_advisory.passed_gates == 1
    assert v_advisory.failed_gates == 1
    assert "advisory check(s) reported warnings" in v_advisory.summary_explanation

    # 4. Required gate failed REJECTS verdict
    r_req_fail = QualityGateResult(
        gate_id="g4",
        gate_type=QualityGateType.TEST,
        name="Pytest Suite",
        status=QualityGateStatus.FAILED,
        required=True,
        evidence=QualityEvidence(summary="1 test failed"),
        failure_reason="AssertionError in test_foo",
    )
    v_fail = QualityVerdict.compute([r1, r_req_fail], verdict_id="v-fail")
    assert v_fail.status == QualityVerdictStatus.REJECTED
    assert v_fail.passed is False
    assert v_fail.failed_gates == 1
    assert "required gate(s) failed: 'Pytest Suite' (g4)" in v_fail.summary_explanation

    # 5. Infrastructure/Execution ERROR on required gate marks ERROR status and blocks acceptance
    r_error = QualityGateResult(
        gate_id="g5",
        gate_type=QualityGateType.BUILD,
        name="Compile Step",
        status=QualityGateStatus.ERROR,
        required=True,
        evidence=QualityEvidence(summary="Executor crashed"),
        failure_reason="Subprocess crashed with SIGSEGV",
    )
    v_error = QualityVerdict.compute([r1, r_error], verdict_id="v-err")
    assert v_error.status == QualityVerdictStatus.ERROR
    assert v_error.passed is False
    assert v_error.error_gates == 1


def test_quality_profile_contract() -> None:
    g1 = QualityGateSpec(gate_id="test-1", gate_type=QualityGateType.TEST, name="T1")
    g2 = QualityGateSpec(gate_id="lint-1", gate_type=QualityGateType.LINT, name="L1")
    profile = QualityProfile(
        profile_id="py-default",
        name="Python Standard Quality Profile",
        target_languages=("python",),
        gates=(g1, g2),
        is_default=True,
    )
    assert profile.profile_id == "py-default"
    assert len(profile.gates) == 2

    # Duplicate gate IDs rejected in profile
    with pytest.raises(
        QualityContractValidationError, match="Duplicate gate_ids detected in profile"
    ):
        QualityProfile(
            profile_id="bad-profile",
            name="Bad Profile",
            gates=(g1, g1),
        )


def test_quality_run_and_repair_packet_contract() -> None:
    now = datetime.now(UTC)
    packet = QualityRepairPacket(
        run_id="qrun-123",
        task_id="task-abc",
        execution_id="exec-456",
        attempt_number=1,
        max_repair_attempts=3,
        blocking_gate_ids=("python-tests",),
        failure_summaries=("Test failed in test_bar",),
        diagnostics=("AssertionError: 1 != 2",),
        affected_artifacts=("src/bar.py",),
        created_at=now,
    )
    assert packet.attempt_number == 1
    assert len(packet.blocking_gate_ids) == 1
    assert "src/bar.py" in packet.affected_artifacts
