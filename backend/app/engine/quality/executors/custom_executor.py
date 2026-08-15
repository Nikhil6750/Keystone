"""Deterministic Command Quality Gate Executor for configured verification commands."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

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


@dataclass(frozen=True)
class TrustedQualityCommand:
    """Server-side registered trusted verification command template."""

    command_id: str
    executable: str
    args_template: tuple[str, ...]
    description: str = ""


class TrustedQualityCommandRegistry:
    """Registry of pre-approved, deterministic verification command templates."""

    _commands: ClassVar[dict[str, TrustedQualityCommand]] = {
        "pytest-check": TrustedQualityCommand(
            command_id="pytest-check",
            executable="pytest",
            args_template=("-q", "{target_path}"),
            description="Run pytest against target path",
        ),
        "unittest-check": TrustedQualityCommand(
            command_id="unittest-check",
            executable="python",
            args_template=("-m", "unittest", "discover", "-s", "{target_path}"),
            description="Run python unittest discover against target path",
        ),
        "ruff-check": TrustedQualityCommand(
            command_id="ruff-check",
            executable="ruff",
            args_template=("check", "{target_path}"),
            description="Run ruff code quality check against target path",
        ),
        "mypy-check": TrustedQualityCommand(
            command_id="mypy-check",
            executable="mypy",
            args_template=("{target_path}",),
            description="Run mypy type checking against target path",
        ),
        "compileall-check": TrustedQualityCommand(
            command_id="compileall-check",
            executable="python",
            args_template=("-m", "compileall", "-q", "{target_path}"),
            description="Run python compileall against target path",
        ),
        "node-test": TrustedQualityCommand(
            command_id="node-test",
            executable="node",
            args_template=("--test", "{target_path}"),
            description="Run node native test runner against target path",
        ),
        "tsc-check": TrustedQualityCommand(
            command_id="tsc-check",
            executable="tsc",
            args_template=("--noEmit",),
            description="Run tsc type check",
        ),
    }

    @classmethod
    def get_command(cls, command_id: str) -> TrustedQualityCommand | None:
        """Lookup a trusted command template by command_id."""
        return cls._commands.get(command_id)

    @classmethod
    def register_command(cls, command: TrustedQualityCommand) -> None:
        """Register a new trusted command template server-side."""
        cls._commands[command.command_id] = command


class DeterministicCommandQualityGateExecutor:
    """Executes server-side registered trusted deterministic quality verification commands.

    Arbitrary untrusted argv from task/skill/planner payload is strictly rejected.
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

        # 1. Unconditional rejection of raw untrusted custom argv
        if "argv" in cfg:
            summary = (
                "Arbitrary raw 'argv' configuration is strictly disallowed for custom gates. "
                "Custom gates must specify a server-side registered 'command_id'."
            )
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

        # 2. Resolve trusted command_id
        command_id = str(
            cfg.get("command_id") or cfg.get("registered_command_id") or spec.gate_id
        ).strip()
        trusted_cmd = TrustedQualityCommandRegistry.get_command(command_id)
        if trusted_cmd is None:
            summary = (
                f"Unapproved or unregistered custom quality command_id: '{command_id}'. "
                "Custom verification commands must use a server-side registered command_id."
            )
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

        # 3. Validate and resolve target_path parameter if specified
        target_path_param = cfg.get("target_path")
        try:
            _, safe_target_str = resolve_and_validate_target_path(
                ws_root, target_path_param, default="."
            )
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

        # 4. Construct concrete argv from trusted template
        concrete_argv: list[str] = [trusted_cmd.executable]
        for arg in trusted_cmd.args_template:
            concrete_argv.append(arg.replace("{target_path}", safe_target_str))

        runner = SafeQualityProcessRunner(ws_root)
        proc_res = runner.run(
            argv=concrete_argv,
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


__all__ = [
    "DeterministicCommandQualityGateExecutor",
    "TrustedQualityCommand",
    "TrustedQualityCommandRegistry",
]
