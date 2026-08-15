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
from app.engine.quality.process import (
    SafeQualityProcessRunner,
    _is_safe_env_key,
    _safe_environment,
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


def test_safe_quality_process_runner_allowlist_enforcement() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        runner = SafeQualityProcessRunner(temp_dir)

        # Unapproved executable rejected
        with pytest.raises(UnapprovedQualityCommandError, match="not permitted"):
            runner.run(argv=["curl", "http://example.com"])

        with pytest.raises(UnapprovedQualityCommandError, match="not permitted"):
            runner.run(argv=["bash", "-c", "echo hello"])


def test_safe_quality_process_runner_python_execution() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        runner = SafeQualityProcessRunner(temp_dir)
        res = runner.run(argv=["python", "-c", "print('Hello Quality')"])
        assert res.exit_code == 0
        assert "Hello Quality" in res.stdout
        assert res.timed_out is False


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


def test_lint_quality_gate_executor() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        ws_root = Path(temp_dir)
        # Create clean python file
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


def test_deterministic_custom_gate_executor() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        ws_root = Path(temp_dir)
        context = QualityExecutionContext(workspace_root=str(ws_root))

        spec = QualityGateSpec(
            gate_id="custom-cmd",
            gate_type=QualityGateType.CUSTOM,
            name="Verify Version",
            required=True,
            configuration={"argv": ["python", "--version"], "expected_exit_code": 0},
        )
        executor = DeterministicCommandQualityGateExecutor()
        res = executor.execute(spec, context)
        assert res.status == QualityGateStatus.PASSED


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
