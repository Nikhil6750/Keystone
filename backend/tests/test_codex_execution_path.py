"""Regression coverage for the production Codex factory/execution path."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.adapters.factory import activate_agent
from app.adapters.process_runner import SubprocessRunner
from app.core.config import Settings
from app.engine.executor import StepExecutionRequest
from app.engine.registry import ExecutorRegistry


def test_codex_coding_execution_is_writable_argv_only_and_uses_workspace_cwd(
    tmp_path: Path,
) -> None:
    """The factory-built adapter must launch writable Codex in the requested workspace."""
    executable = str(tmp_path / "codex.exe")
    settings = Settings(codex_enabled=False, codex_executable="codex")
    registry = ExecutorRegistry()
    strategy = MagicMock(execution_supported=True)
    strategy.find_executable.return_value = executable
    completed = MagicMock(
        returncode=0,
        stdout=json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "files created"},
            }
        ),
        stderr="",
    )

    with (
        patch("app.adapters.factory.get_discovery_strategy", return_value=strategy),
        patch("app.adapters.process_runner.shutil.which", return_value=executable),
        patch("app.adapters.process_runner.subprocess.run", return_value=completed) as run,
    ):
        assert activate_agent(
            registry,
            settings,
            "codex",
            process_runner=SubprocessRunner(),
        )
        result = registry.get("codex").execute(
            StepExecutionRequest(
                workflow_id="wf-codex-write",
                step_id="step-codex-write",
                step_name="build project",
                agent_type="codex",
                step_input={},
                workflow_input={},
                previous_step_outputs={},
                workspace_root=str(tmp_path),
            )
        )

    expected_arguments = [
        "exec",
        "--json",
        "--ephemeral",
        "--sandbox",
        "workspace-write",
        "--skip-git-repo-check",
    ]
    command = run.call_args.args[0]
    assert command == [executable, *expected_arguments]
    assert isinstance(command, list)
    assert "read-only" not in command
    assert run.call_args.kwargs["cwd"] == str(tmp_path)
    assert run.call_args.kwargs["shell"] is False
    assert result["content"] == "files created"
