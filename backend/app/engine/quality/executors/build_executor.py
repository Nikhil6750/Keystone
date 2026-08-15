"""Build Quality Gate Executor for verifying software compilation / build integrity."""

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
from app.engine.quality.process import SafeQualityProcessRunner


class BuildQualityGateExecutor:
    """Executes compile or build verification (e.g. py_compile, tsc, npm run build)

    to ensure software artifacts build cleanly without syntax or compilation failures.
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

        runner = SafeQualityProcessRunner(ws_root)
        cfg = spec.configuration or {}
        builder = cfg.get("builder", "auto")
        target_path = cfg.get("target_path", ".")

        is_node = any(lang in ("javascript", "typescript", "node") for lang in context.languages)

        if builder == "npm" or (is_node and builder == "auto"):
            argv = ["npm", "run", "build"]
        else:
            # Default to Python compilation check
            argv = ["python", "-m", "compileall", "-q", target_path]

        proc_res = runner.run(
            argv=argv,
            timeout_seconds=spec.timeout_seconds,
            env_overrides=context.environment_overrides,
        )

        metrics = {"exit_code": proc_res.exit_code}
        diagnostics: list[str] = []
        if proc_res.stderr:
            diagnostics = [
                line.strip()[:200] for line in proc_res.stderr.splitlines() if line.strip()
            ][:10]

        if proc_res.timed_out:
            summary = f"Build verification timed out after {spec.timeout_seconds}s."
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

        if proc_res.exit_code == 0:
            summary = "Build verification completed successfully."
            evidence = QualityEvidence(
                summary=summary,
                exit_code=0,
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

        summary = f"Build verification failed with exit code {proc_res.exit_code}."
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


__all__ = ["BuildQualityGateExecutor"]
