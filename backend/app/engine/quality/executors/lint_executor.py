"""Lint Quality Gate Executor for running static analysis and linters."""

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


class LintQualityGateExecutor:
    """Executes linting / static analysis (e.g. ruff, eslint) on workspace code

    and collects structured violation diagnostics and metrics.
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
        linter = cfg.get("linter", "auto")

        is_node = any(lang in ("javascript", "typescript", "node") for lang in context.languages)

        if linter == "eslint" or (is_node and linter == "auto"):
            argv = ["npx", "eslint", target_path]
        else:
            # Default to Ruff for Python / generic
            argv = ["python", "-m", "ruff", "check", target_path]

        proc_res = runner.run(
            argv=argv,
            timeout_seconds=spec.timeout_seconds,
            env_overrides=context.environment_overrides,
        )

        diagnostics = self._extract_lint_diagnostics(proc_res.stdout, proc_res.stderr)
        violations_count = len(diagnostics)
        metrics = {"violations_count": violations_count, "exit_code": proc_res.exit_code}

        if proc_res.timed_out:
            summary = f"Lint check timed out after {spec.timeout_seconds}s."
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
            summary = "Lint check passed with 0 violations."
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

        summary = f"Lint check failed: {violations_count or 1} violation(s) detected."
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

    def _extract_lint_diagnostics(self, stdout: str, stderr: str) -> list[str]:
        diagnostics: list[str] = []
        combined = f"{stdout}\n{stderr}"
        for line in combined.splitlines():
            line_str = line.strip()
            if (
                line_str
                and not line_str.startswith("Found ")
                and not line_str.startswith("All checks passed")
                and any(
                    ind in line_str for ind in (": error", ": warning", "E", "F", "W", "I", "C")
                )
                and line_str not in diagnostics
            ):
                diagnostics.append(line_str[:200])
        return diagnostics[:20]


__all__ = ["LintQualityGateExecutor"]
