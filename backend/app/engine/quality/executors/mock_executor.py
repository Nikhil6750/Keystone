"""Mock Quality Gate Executor for testing and simulated gate executions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.contracts.quality import (
    QualityEvidence,
    QualityExecutionContext,
    QualityGateResult,
    QualityGateSpec,
    QualityGateStatus,
)


class MockQualityGateExecutor:
    """Configurable mock executor that returns predefined or simulated results for testing."""

    def __init__(
        self,
        default_status: QualityGateStatus = QualityGateStatus.PASSED,
        overrides: dict[str, QualityGateStatus] | None = None,
        custom_evidence: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.default_status = default_status
        self.overrides = overrides or {}
        self.custom_evidence = custom_evidence or {}
        self.executed_specs: list[QualityGateSpec] = []

    def execute(
        self,
        spec: QualityGateSpec,
        context: QualityExecutionContext,
    ) -> QualityGateResult:
        self.executed_specs.append(spec)
        status = self.overrides.get(spec.gate_id, self.default_status)
        ev_data = self.custom_evidence.get(spec.gate_id, {})

        failure_reason = None
        if status in (QualityGateStatus.FAILED, QualityGateStatus.ERROR):
            failure_reason = ev_data.get("summary", f"Simulated failure for gate '{spec.name}'")

        evidence = QualityEvidence(
            summary=ev_data.get("summary", f"Mock execution of gate '{spec.name}'"),
            exit_code=ev_data.get("exit_code", 0 if status is QualityGateStatus.PASSED else 1),
            diagnostics=tuple(ev_data.get("diagnostics", [])),
            artifact_references=tuple(ev_data.get("artifact_references", [])),
            stdout=ev_data.get("stdout", ""),
            stderr=ev_data.get("stderr", ""),
            metrics=dict(ev_data.get("metrics", {})),
        )

        return QualityGateResult(
            gate_id=spec.gate_id,
            gate_type=spec.gate_type,
            name=spec.name,
            status=status,
            required=spec.required,
            evidence=evidence,
            execution_time_ms=10.0,
            failure_reason=failure_reason,
            timestamp=datetime.now(UTC),
        )


__all__ = ["MockQualityGateExecutor"]
