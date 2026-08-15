"""Deterministic Command Quality Gate Executor for configured verification commands."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.contracts.quality import (
    QualityEvidence,
    QualityExecutionContext,
    QualityGateResult,
    QualityGateSpec,
    QualityGateStatus,
)
from app.engine.quality.errors import QualitySecurityError
from app.engine.quality.process import SafeQualityProcessRunner


class DeterministicCommandQualityGateExecutor:
    """Executes pre-registered or explicitly configured deterministic quality
    verification commands.
    """

    def execute(
        self,
        spec: QualityGateSpec,
        context: QualityExecutionContext,
    ) -> QualityGateResult:
        ws_root = Path(context.workspace_root)
        if not ws_root.is_dir():
            evidence = QualityEvidence(
                summary=f"Workspace root not found: {context.workspace_root}"
            )
            return QualityGateResult(
                gate_id=spec.gate_id,
                gate_type=spec.gate_type,
                name=spec.name,
                status=QualityGateStatus.ERROR,
                required=spec.required,
                evidence=evidence,
                failure_reason=f"Workspace root not found: {context.workspace_root}",
                timestamp=datetime.now(UTC),
            )

        cfg = spec.configuration or {}
        argv = cfg.get("argv")
        if not argv or not isinstance(argv, (list, tuple)):
            evidence = QualityEvidence(summary="Custom gate configuration missing 'argv' array.")
            return QualityGateResult(
                gate_id=spec.gate_id,
                gate_type=spec.gate_type,
                name=spec.name,
                status=QualityGateStatus.ERROR,
                required=spec.required,
                evidence=evidence,
                failure_reason="Custom gate configuration missing 'argv' array",
                timestamp=datetime.now(UTC),
            )

        # Validate argv items are strings
        if any(not isinstance(arg, str) for arg in argv):
            raise QualitySecurityError("argv must contain only string arguments")

        runner = SafeQualityProcessRunner(ws_root)
        proc_res = runner.run(
            argv=list(argv),
            timeout_seconds=spec.timeout_seconds,
            env_overrides=context.environment_overrides,
        )

        expected_exit_code = int(cfg.get("expected_exit_code", 0))
        metrics = {"exit_code": proc_res.exit_code, "expected_exit_code": expected_exit_code}
        diagnostics = [line.strip()[:200] for line in proc_res.stderr.splitlines() if line.strip()][
            :10
        ]

        if proc_res.timed_out:
            summary = f"Command timed out after {spec.timeout_seconds}s."
            evidence = QualityEvidence(
                summary=summary,
                exit_code=proc_res.exit_code,
                diagnostics=tuple(diagnostics),
                stdout=proc_res.stdout,
                stderr=proc_res.stderr,
                metrics=metrics,
            )
            return QualityGateResult(
                gate_id=spec.gate_id,
                gate_type=spec.gate_type,
                name=spec.name,
                status=QualityGateStatus.FAILED,
                required=spec.required,
                evidence=evidence,
                execution_time_ms=proc_res.duration_ms,
                failure_reason=summary,
                timestamp=datetime.now(UTC),
            )

        if proc_res.exit_code == expected_exit_code:
            summary = f"Command passed (exit code {proc_res.exit_code})."
            evidence = QualityEvidence(
                summary=summary,
                exit_code=proc_res.exit_code,
                diagnostics=(),
                stdout=proc_res.stdout,
                stderr=proc_res.stderr,
                metrics=metrics,
            )
            return QualityGateResult(
                gate_id=spec.gate_id,
                gate_type=spec.gate_type,
                name=spec.name,
                status=QualityGateStatus.PASSED,
                required=spec.required,
                evidence=evidence,
                execution_time_ms=proc_res.duration_ms,
                timestamp=datetime.now(UTC),
            )

        summary = (
            f"Command failed: expected exit code {expected_exit_code}, got {proc_res.exit_code}."
        )
        evidence = QualityEvidence(
            summary=summary,
            exit_code=proc_res.exit_code,
            diagnostics=tuple(diagnostics),
            stdout=proc_res.stdout,
            stderr=proc_res.stderr,
            metrics=metrics,
        )
        return QualityGateResult(
            gate_id=spec.gate_id,
            gate_type=spec.gate_type,
            name=spec.name,
            status=QualityGateStatus.FAILED,
            required=spec.required,
            evidence=evidence,
            execution_time_ms=proc_res.duration_ms,
            failure_reason=summary,
            timestamp=datetime.now(UTC),
        )


__all__ = ["DeterministicCommandQualityGateExecutor"]
