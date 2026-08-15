"""Type Check Quality Gate Executor for running static type analysis."""

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
from app.engine.quality.process import (
    SafeQualityProcessRunner,
    resolve_and_validate_target_path,
)


class TypeCheckQualityGateExecutor:
    """Executes static type checking (e.g. mypy, tsc) on workspace code

    and collects structured type error diagnostics and metrics.
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
        raw_target = cfg.get("target_path", ".")
        try:
            _, target_path = resolve_and_validate_target_path(ws_root, raw_target, default=".")
        except QualitySecurityError as exc:
            summary = f"Target path validation failed: {exc}"
            evidence = QualityEvidence(summary=summary)
            return QualityGateResult(
                gate_id=spec.gate_id,
                gate_type=spec.gate_type,
                name=spec.name,
                status=QualityGateStatus.ERROR,
                required=spec.required,
                evidence=evidence,
                failure_reason=summary,
                timestamp=datetime.now(UTC),
            )

        runner = SafeQualityProcessRunner(ws_root)
        type_checker = cfg.get("type_checker", "auto")

        is_ts = any(lang in ("typescript", "ts") for lang in context.languages)

        if type_checker == "tsc" or (is_ts and type_checker == "auto"):
            argv = ["npx", "tsc", "--noEmit"]
        else:
            # Default to mypy for Python / generic
            argv = ["python", "-m", "mypy", target_path]

        proc_res = runner.run(
            argv=argv,
            timeout_seconds=spec.timeout_seconds,
            env_overrides=context.environment_overrides,
        )

        diagnostics = self._extract_type_diagnostics(proc_res.stdout, proc_res.stderr)
        type_errors_count = len(diagnostics)
        metrics = {"type_errors_count": type_errors_count, "exit_code": proc_res.exit_code}

        if proc_res.timed_out:
            summary = f"Type check timed out after {spec.timeout_seconds}s."
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
            summary = "Type check passed with 0 errors."
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

        summary = f"Type check failed: {type_errors_count or 1} error(s) detected."
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

    def _extract_type_diagnostics(self, stdout: str, stderr: str) -> list[str]:
        diagnostics: list[str] = []
        combined = f"{stdout}\n{stderr}"
        for line in combined.splitlines():
            line_str = line.strip()
            if (": error:" in line_str or "TS" in line_str) and line_str not in diagnostics:
                diagnostics.append(line_str[:200])
        return diagnostics[:20]


__all__ = ["TypeCheckQualityGateExecutor"]
