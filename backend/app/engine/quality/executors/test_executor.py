"""Test Quality Gate Executor for running automated test suites in a workspace."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.contracts.quality import (
    QualityEvidence,
    QualityExecutionContext,
    QualityGateResult,
    QualityGateSpec,
    QualityGateStatus,
)
from app.engine.quality.process import SafeQualityProcessRunner

_PYTEST_SUMMARY_RE = re.compile(
    r"=+\s*(?:(?P<passed>\d+)\s+passed)?(?:,\s*)?(?:(?P<failed>\d+)\s+failed)?(?:,\s*)?(?:(?P<errors>\d+)\s+errors?)?(?:,\s*)?(?:(?P<skipped>\d+)\s+skipped)?.*=+",
    re.IGNORECASE,
)
_UNITTEST_RAN_RE = re.compile(r"Ran (\d+) tests? in [0-9.]+s")
_UNITTEST_FAIL_RE = re.compile(
    r"FAILED \((?:failures=(?P<failures>\d+))?(?:, )?(?:errors=(?P<errors>\d+))?\)"
)
_TAP_COUNT_RE = re.compile(r"^# (?:tests|pass|fail) (\d+)$", re.MULTILINE)


class TestQualityGateExecutor:
    """Executes automated test suites (pytest, python unittest, node --test)

    against workspace artifacts and extracts structured test metrics and diagnostics.
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
        runner_type = cfg.get("runner", "auto")
        target_path = cfg.get("target_path")

        # 1. Determine command arguments based on language/framework/configuration
        argv: list[str] = []
        is_node = any(lang in ("javascript", "typescript", "node") for lang in context.languages)

        if runner_type == "node" or is_node:
            test_files = self._find_node_test_files(ws_root, target_path)
            if not test_files and not target_path:
                evidence = QualityEvidence(summary="No Node.js test files found in workspace.")
                return QualityGateResult(
                    gate_id=spec.gate_id,
                    gate_type=spec.gate_type,
                    name=spec.name,
                    status=QualityGateStatus.SKIPPED,
                    required=spec.required,
                    evidence=evidence,
                    skip_reason="No Node.js test files discovered in workspace.",
                    timestamp=datetime.now(UTC),
                )
            argv = ["node", "--test"] + (test_files if not target_path else [str(target_path)])
        else:
            # Default to Python test execution
            test_files = self._find_python_test_files(ws_root, target_path)
            if not test_files and not target_path:
                evidence = QualityEvidence(summary="No Python test files found in workspace.")
                return QualityGateResult(
                    gate_id=spec.gate_id,
                    gate_type=spec.gate_type,
                    name=spec.name,
                    status=QualityGateStatus.SKIPPED,
                    required=spec.required,
                    evidence=evidence,
                    skip_reason="No Python test files discovered in workspace.",
                    timestamp=datetime.now(UTC),
                )

            # Use pytest or unittest
            if runner_type == "unittest":
                argv = ["python", "-m", "unittest", "discover", "-s", target_path or "."]
            else:
                argv = ["python", "-m", "pytest", "-q"]
                if target_path:
                    argv.append(target_path)

        # 2. Execute process defensively
        proc_res = runner.run(
            argv=argv,
            timeout_seconds=spec.timeout_seconds,
            env_overrides=context.environment_overrides,
        )

        metrics = self._parse_test_metrics(proc_res.stdout, proc_res.stderr)
        diagnostics = self._extract_failure_diagnostics(proc_res.stdout, proc_res.stderr)

        if proc_res.timed_out:
            summary = f"Test execution timed out after {spec.timeout_seconds}s."
            evidence = QualityEvidence(
                summary=summary,
                exit_code=proc_res.exit_code,
                diagnostics=tuple(diagnostics) or ("Process timed out",),
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
            passed_count = metrics.get("passed", 0)
            summary = f"All tests passed successfully ({passed_count} passed)."
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

        # Test failure
        failed_count = metrics.get("failed", 0) + metrics.get("errors", 0)
        summary = (
            f"Test execution failed (exit code {proc_res.exit_code}): "
            f"{failed_count} failures detected."
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

    def _find_python_test_files(self, root: Path, target_path: str | None) -> list[str]:
        if target_path and (root / target_path).exists():
            return [target_path]
        matches: list[str] = []
        for p in root.rglob("*.py"):
            if (p.name.startswith("test_") or p.name.endswith("_test.py")) and not any(
                part in (".venv", "node_modules", ".git") for part in p.parts
            ):
                matches.append(str(p.relative_to(root).as_posix()))
        return sorted(matches)

    def _find_node_test_files(self, root: Path, target_path: str | None) -> list[str]:
        if target_path and (root / target_path).exists():
            return [target_path]
        matches: list[str] = []
        for p in root.rglob("*"):
            if (
                p.is_file()
                and (
                    p.name.endswith(".test.js")
                    or p.name.endswith(".spec.js")
                    or p.name.endswith(".test.mjs")
                )
                and not any(part in ("node_modules", ".git") for part in p.parts)
            ):
                matches.append(str(p.relative_to(root).as_posix()))
        return sorted(matches)

    def _parse_test_metrics(self, stdout: str, stderr: str) -> dict[str, Any]:
        metrics: dict[str, Any] = {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
        }
        combined = f"{stdout}\n{stderr}"

        # Pytest parser
        pytest_match = _PYTEST_SUMMARY_RE.search(combined)
        if pytest_match:
            p = int(pytest_match.group("passed") or 0)
            f = int(pytest_match.group("failed") or 0)
            e = int(pytest_match.group("errors") or 0)
            s = int(pytest_match.group("skipped") or 0)
            metrics.update(
                {"total": p + f + e + s, "passed": p, "failed": f, "errors": e, "skipped": s}
            )
            return metrics

        # Unittest parser
        unittest_ran = _UNITTEST_RAN_RE.search(combined)
        if unittest_ran:
            tot = int(unittest_ran.group(1))
            fail_match = _UNITTEST_FAIL_RE.search(combined)
            f = int(fail_match.group("failures") or 0) if fail_match else 0
            e = int(fail_match.group("errors") or 0) if fail_match else 0
            metrics.update(
                {
                    "total": tot,
                    "passed": max(0, tot - f - e),
                    "failed": f,
                    "errors": e,
                    "skipped": 0,
                }
            )
            return metrics

        return metrics

    def _extract_failure_diagnostics(self, stdout: str, stderr: str) -> list[str]:
        diagnostics: list[str] = []
        combined = f"{stdout}\n{stderr}"
        for line in combined.splitlines():
            line_str = line.strip()
            if (
                any(
                    token in line_str
                    for token in (
                        "FAILED ",
                        "ERROR: ",
                        "AssertionError",
                        "SyntaxError",
                        "ImportError",
                        "Traceback",
                    )
                )
                and line_str
                and line_str not in diagnostics
            ):
                diagnostics.append(line_str[:200])
        return diagnostics[:15]


__all__ = ["TestQualityGateExecutor"]
