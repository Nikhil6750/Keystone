"""Unit tests for SafeQualityProcessRunner and built-in Quality Gate Executors."""

import os
import tempfile
from pathlib import Path

import pytest

from app.contracts.quality import (
    QualityExecutionContext,
    QualityGateSpec,
    QualityGateStatus,
    QualityGateType,
)
from app.engine.quality.errors import (
    QualitySecurityError,
    UnapprovedQualityCommandError,
)
from app.engine.quality.executors import (
    BuildQualityGateExecutor,
    DeterministicCommandQualityGateExecutor,
    LintQualityGateExecutor,
    MockQualityGateExecutor,
    TestQualityGateExecutor,
    TypeCheckQualityGateExecutor,
)
from app.engine.quality.executors.custom_executor import (
    TrustedQualityCommand,
    TrustedQualityCommandRegistry,
)
from app.engine.quality.process import (
    SafeQualityProcessRunner,
    _is_safe_env_key,
    _safe_environment,
    resolve_and_validate_target_path,
    validate_workspace_path,
)
from app.engine.quality.registry import QualityGateExecutorRegistry


def test_safe_environment_strips_sensitive_keys() -> None:
    os.environ["SUPER_SECRET_KEY"] = "super-secret"
    os.environ["BEARER_AUTH_TOKEN"] = "token123"
    env = _safe_environment({"CUSTOM_VAR": "val", "MY_API_KEY": "forbidden"})
    assert "SUPER_SECRET_KEY" not in env
    assert "BEARER_AUTH_TOKEN" not in env
    assert "MY_API_KEY" not in env
    assert env.get("CUSTOM_VAR") == "val"
    assert _is_safe_env_key("PATH") is True
    assert _is_safe_env_key("API_KEY") is False


def test_validate_workspace_path_containment() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        ws_root = Path(temp_dir).resolve()
        sub_dir = ws_root / "subdir"
        sub_dir.mkdir()

        # Valid subpath
        assert validate_workspace_path(sub_dir, ws_root) == sub_dir

        # Path escape rejected
        outside_path = ws_root.parent
        with pytest.raises(QualitySecurityError, match="Path escape violation"):
            validate_workspace_path(outside_path, ws_root)

        # resolve_and_validate_target_path tests
        _, safe_rel = resolve_and_validate_target_path(ws_root, "subdir")
        assert safe_rel == "subdir"

        # Traversal rejected
        with pytest.raises(QualitySecurityError, match="Path escape violation"):
            resolve_and_validate_target_path(ws_root, "../outside")

        # Absolute outside path rejected
        with pytest.raises(QualitySecurityError, match="Path escape violation"):
            resolve_and_validate_target_path(ws_root, str(ws_root.parent))


def test_safe_quality_process_runner_allowlist_enforcement() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        runner = SafeQualityProcessRunner(temp_dir)

        # Unapproved executable rejected
        with pytest.raises(UnapprovedQualityCommandError, match="not permitted"):
            runner.run(argv=["curl", "http://example.com"])

        with pytest.raises(UnapprovedQualityCommandError, match="not permitted"):
            runner.run(argv=["bash", "-c", "echo hello"])


def test_safe_quality_process_runner_rejects_arbitrary_code_evaluation() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        runner = SafeQualityProcessRunner(temp_dir)

        # python -c is rejected
        with pytest.raises(QualitySecurityError, match="arbitrary Python code strings"):
            runner.run(argv=["python", "-c", "print('arbitrary code')"])

        # node -e / --eval is rejected
        with pytest.raises(QualitySecurityError, match="arbitrary Node.js code strings"):
            runner.run(argv=["node", "-e", "process.exit(1)"])

        with pytest.raises(QualitySecurityError, match="arbitrary Node.js code strings"):
            runner.run(argv=["node", "--eval", "console.log('hi')"])

        # Arbitrary npx package is rejected
        with pytest.raises(QualitySecurityError, match="not in approved verification tools"):
            runner.run(argv=["npx", "malicious-package"])


def test_test_quality_gate_executor_mock_and_discovery() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        ws_root = Path(temp_dir)

        # 1. No test files -> SKIPPED
        context = QualityExecutionContext(workspace_root=str(ws_root), languages=("python",))
        spec = QualityGateSpec(
            gate_id="python-tests",
            gate_type=QualityGateType.TEST,
            name="Python Tests",
            required=True,
        )
        executor = TestQualityGateExecutor()
        res_skipped = executor.execute(spec, context)
        assert res_skipped.status == QualityGateStatus.SKIPPED
        assert "No Python test files" in (res_skipped.skip_reason or "")

        # 2. Add passing test file
        test_file = ws_root / "test_sample.py"
        test_file.write_text("def test_ok(): assert 1 == 1\n", encoding="utf-8")

        res_passed = executor.execute(spec, context)
        assert res_passed.status == QualityGateStatus.PASSED
        assert res_passed.evidence.exit_code == 0

        # 3. Path traversal in target_path returns ERROR
        spec_bad_path = QualityGateSpec(
            gate_id="python-tests-bad",
            gate_type=QualityGateType.TEST,
            name="Python Tests Traversal",
            required=True,
            configuration={"target_path": "../../outside"},
        )
        res_bad = executor.execute(spec_bad_path, context)
        assert res_bad.status == QualityGateStatus.ERROR
        assert "Target path validation failed" in (res_bad.failure_reason or "")


def test_lint_quality_gate_executor() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        ws_root = Path(temp_dir)
        code_file = ws_root / "module.py"
        code_file.write_text("x = 1\n", encoding="utf-8")

        context = QualityExecutionContext(workspace_root=str(ws_root), languages=("python",))
        spec = QualityGateSpec(
            gate_id="python-lint",
            gate_type=QualityGateType.LINT,
            name="Ruff Linter",
            required=True,
        )
        executor = LintQualityGateExecutor()
        res = executor.execute(spec, context)
        assert res.status == QualityGateStatus.PASSED


def test_deterministic_custom_gate_executor_and_trusted_registry() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        ws_root = Path(temp_dir)
        code_file = ws_root / "sample.py"
        code_file.write_text("a = 10\n", encoding="utf-8")

        context = QualityExecutionContext(workspace_root=str(ws_root))

        # 1. Custom raw argv without registered command is rejected
        spec_raw_argv = QualityGateSpec(
            gate_id="custom-raw",
            gate_type=QualityGateType.CUSTOM,
            name="Raw Argv Attempt",
            required=True,
            configuration={"argv": ["python", "-c", "import os"]},
        )
        executor = DeterministicCommandQualityGateExecutor()
        res_raw = executor.execute(spec_raw_argv, context)
        assert res_raw.status == QualityGateStatus.ERROR
        assert "Arbitrary raw 'argv' configuration is strictly disallowed" in (
            res_raw.failure_reason or ""
        )

        # 2. Unregistered command_id is rejected
        spec_unregistered = QualityGateSpec(
            gate_id="custom-unreg",
            gate_type=QualityGateType.CUSTOM,
            name="Unregistered Command",
            required=True,
            configuration={"command_id": "unregistered-command-xyz"},
        )
        res_unreg = executor.execute(spec_unregistered, context)
        assert res_unreg.status == QualityGateStatus.ERROR
        assert "Unapproved or unregistered custom quality command_id" in (
            res_unreg.failure_reason or ""
        )

        # 3. Server-side registered trusted command executes successfully
        TrustedQualityCommandRegistry.register_command(
            TrustedQualityCommand(
                command_id="test-compile-trusted",
                executable="python",
                args_template=("-m", "compileall", "-q", "{target_path}"),
                description="Trusted compileall command",
            )
        )
        spec_trusted = QualityGateSpec(
            gate_id="custom-trusted",
            gate_type=QualityGateType.CUSTOM,
            name="Trusted Compile",
            required=True,
            configuration={"command_id": "test-compile-trusted", "target_path": "sample.py"},
        )
        res_trusted = executor.execute(spec_trusted, context)
        assert res_trusted.status == QualityGateStatus.PASSED


def test_executor_registry() -> None:
    reg = QualityGateExecutorRegistry.default_registry()
    assert isinstance(reg.get_executor(QualityGateType.TEST), TestQualityGateExecutor)
    assert isinstance(reg.get_executor(QualityGateType.LINT), LintQualityGateExecutor)
    assert isinstance(reg.get_executor(QualityGateType.TYPE_CHECK), TypeCheckQualityGateExecutor)
    assert isinstance(reg.get_executor(QualityGateType.BUILD), BuildQualityGateExecutor)
    assert isinstance(
        reg.get_executor(QualityGateType.CUSTOM), DeterministicCommandQualityGateExecutor
    )

    mock_exec = MockQualityGateExecutor()
    reg.register_executor(QualityGateType.TEST, mock_exec)
    assert reg.get_executor(QualityGateType.TEST) is mock_exec
