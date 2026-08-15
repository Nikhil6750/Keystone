"""Tests for the safe subprocess execution boundary."""

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from app.adapters.exceptions import (
    AgentOutputError,
    AgentProcessError,
    AgentTimeoutError,
    AgentUnavailableError,
)
from app.adapters.process_runner import SubprocessRunner


def _completed(returncode: int = 0, stdout: str = "ok", stderr: str = "") -> MagicMock:
    completed = MagicMock()
    completed.returncode = returncode
    completed.stdout = stdout
    completed.stderr = stderr
    return completed


def test_shell_is_never_used() -> None:
    runner = SubprocessRunner()
    with (
        patch("app.adapters.process_runner.shutil.which", return_value="/usr/bin/mock"),
        patch("app.adapters.process_runner.subprocess.run", return_value=_completed()) as mock_run,
    ):
        runner.run(
            "mock", ["--flag"], stdin_text=None, timeout_seconds=5.0, max_output_characters=1000
        )
    assert mock_run.call_args.kwargs["shell"] is False


def test_arguments_remain_a_list() -> None:
    runner = SubprocessRunner()
    with (
        patch("app.adapters.process_runner.shutil.which", return_value="/usr/bin/mock"),
        patch("app.adapters.process_runner.subprocess.run", return_value=_completed()) as mock_run,
    ):
        runner.run(
            "mock",
            ["--a", "b", "c"],
            stdin_text=None,
            timeout_seconds=5.0,
            max_output_characters=1000,
        )
    command = mock_run.call_args.args[0]
    assert isinstance(command, list)
    assert command == ["/usr/bin/mock", "--a", "b", "c"]


def test_prompt_passed_via_stdin_when_configured() -> None:
    runner = SubprocessRunner()
    with (
        patch("app.adapters.process_runner.shutil.which", return_value="/usr/bin/mock"),
        patch("app.adapters.process_runner.subprocess.run", return_value=_completed()) as mock_run,
    ):
        runner.run(
            "mock", [], stdin_text="hello prompt", timeout_seconds=5.0, max_output_characters=1000
        )
    assert mock_run.call_args.kwargs["input"] == "hello prompt"
    assert "stdin" not in mock_run.call_args.kwargs


def test_stdin_devnull_when_no_prompt_configured() -> None:
    runner = SubprocessRunner()
    with (
        patch("app.adapters.process_runner.shutil.which", return_value="/usr/bin/mock"),
        patch("app.adapters.process_runner.subprocess.run", return_value=_completed()) as mock_run,
    ):
        runner.run("mock", [], stdin_text=None, timeout_seconds=5.0, max_output_characters=1000)
    assert mock_run.call_args.kwargs["stdin"] is subprocess.DEVNULL
    assert "input" not in mock_run.call_args.kwargs


def test_timeout_maps_to_agent_timeout_error() -> None:
    runner = SubprocessRunner()
    with (
        patch("app.adapters.process_runner.shutil.which", return_value="/usr/bin/mock"),
        patch(
            "app.adapters.process_runner.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["mock"], timeout=5.0),
        ),
        pytest.raises(AgentTimeoutError),
    ):
        runner.run("mock", [], stdin_text=None, timeout_seconds=5.0, max_output_characters=1000)


def test_missing_executable_maps_to_agent_unavailable_error() -> None:
    runner = SubprocessRunner()
    with (
        patch("app.adapters.process_runner.shutil.which", return_value=None),
        pytest.raises(AgentUnavailableError),
    ):
        runner.run(
            "does-not-exist",
            [],
            stdin_text=None,
            timeout_seconds=5.0,
            max_output_characters=1000,
        )


def test_nonzero_exit_maps_to_agent_process_error() -> None:
    runner = SubprocessRunner()
    with (
        patch("app.adapters.process_runner.shutil.which", return_value="/usr/bin/mock"),
        patch(
            "app.adapters.process_runner.subprocess.run",
            return_value=_completed(returncode=1, stderr="boom"),
        ),
        pytest.raises(AgentProcessError),
    ):
        runner.run("mock", [], stdin_text=None, timeout_seconds=5.0, max_output_characters=1000)


def test_oversized_output_is_rejected() -> None:
    runner = SubprocessRunner()
    with (
        patch("app.adapters.process_runner.shutil.which", return_value="/usr/bin/mock"),
        patch(
            "app.adapters.process_runner.subprocess.run",
            return_value=_completed(stdout="x" * 100),
        ),
        pytest.raises(AgentOutputError),
    ):
        runner.run("mock", [], stdin_text=None, timeout_seconds=5.0, max_output_characters=10)


def test_temporary_working_directory_is_cleaned_up() -> None:
    captured_cwd: list[str] = []

    def _fake_run(*args: object, **kwargs: object) -> MagicMock:
        cwd = kwargs.get("cwd")
        assert isinstance(cwd, str)
        captured_cwd.append(cwd)
        return _completed()

    runner = SubprocessRunner()
    with (
        patch("app.adapters.process_runner.shutil.which", return_value="/usr/bin/mock"),
        patch("app.adapters.process_runner.subprocess.run", side_effect=_fake_run),
    ):
        runner.run("mock", [], stdin_text=None, timeout_seconds=5.0, max_output_characters=1000)

    assert len(captured_cwd) == 1
    assert not os.path.exists(captured_cwd[0])


def test_explicit_cwd_is_used_verbatim_and_never_deleted(tmp_path: object) -> None:
    """A real coding-agent step (Stage 8C.3) passes its already-validated
    workspace directory as `cwd`; the runner must use it exactly, and --
    unlike its own fallback temp directory -- must never delete it, since
    the caller (not this call) owns that directory's lifetime."""
    workspace = str(tmp_path)
    captured_cwd: list[str] = []

    def _fake_run(*args: object, **kwargs: object) -> MagicMock:
        cwd = kwargs.get("cwd")
        assert isinstance(cwd, str)
        captured_cwd.append(cwd)
        return _completed()

    runner = SubprocessRunner()
    with (
        patch("app.adapters.process_runner.shutil.which", return_value="/usr/bin/mock"),
        patch("app.adapters.process_runner.subprocess.run", side_effect=_fake_run),
    ):
        runner.run(
            "mock",
            [],
            stdin_text=None,
            timeout_seconds=5.0,
            max_output_characters=1000,
            cwd=workspace,
        )

    assert captured_cwd == [workspace]
    assert os.path.exists(workspace)  # never deleted -- caller-owned


def test_explicit_cwd_survives_a_process_failure_without_being_deleted(tmp_path: object) -> None:
    workspace = str(tmp_path)
    runner = SubprocessRunner()
    with (
        patch("app.adapters.process_runner.shutil.which", return_value="/usr/bin/mock"),
        patch(
            "app.adapters.process_runner.subprocess.run",
            return_value=_completed(returncode=1, stderr="boom"),
        ),
        pytest.raises(AgentProcessError),
    ):
        runner.run(
            "mock",
            [],
            stdin_text=None,
            timeout_seconds=5.0,
            max_output_characters=1000,
            cwd=workspace,
        )

    assert os.path.exists(workspace)


def test_temp_directory_cleanup_survives_a_transient_windows_file_lock() -> None:
    """Regression test for a real bug: Google Antigravity's `agy.exe` was observed
    on Windows to briefly hold a file handle open inside its working directory
    after `subprocess.run` returned, causing an immediate `shutil.rmtree` to raise
    `PermissionError: [WinError 32]` and the whole `/agents/antigravity/verify`
    call to fail with a `500 INTERNAL_ERROR` even though the CLI call itself had
    already succeeded. The runner must retry cleanup and never let a transient
    cleanup race surface as (or mask) an execution failure."""
    runner = SubprocessRunner()
    call_count = {"n": 0}

    def _flaky_rmtree(path: str, *args: object, **kwargs: object) -> None:
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise PermissionError(
                32, "The process cannot access the file because it is being used by another process"
            )

    with (
        patch("app.adapters.process_runner.shutil.which", return_value="/usr/bin/mock"),
        patch("app.adapters.process_runner.subprocess.run", return_value=_completed(stdout="hi")),
        patch("app.adapters.process_runner.shutil.rmtree", side_effect=_flaky_rmtree),
        patch("app.adapters.process_runner.time.sleep"),
    ):
        result = runner.run(
            "mock", [], stdin_text=None, timeout_seconds=5.0, max_output_characters=1000
        )

    assert result.stdout == "hi"
    assert call_count["n"] == 3


def test_temp_directory_cleanup_gives_up_after_retries_without_raising() -> None:
    """Even if cleanup never succeeds, `run()` must still return the real result —
    a stuck temp-directory removal must never be reported as an execution failure."""
    runner = SubprocessRunner()

    def _always_locked(path: str, *args: object, **kwargs: object) -> None:
        raise PermissionError(32, "still locked")

    with (
        patch("app.adapters.process_runner.shutil.which", return_value="/usr/bin/mock"),
        patch("app.adapters.process_runner.subprocess.run", return_value=_completed(stdout="hi")),
        patch(
            "app.adapters.process_runner.shutil.rmtree", side_effect=_always_locked
        ) as mock_rmtree,
        patch("app.adapters.process_runner.time.sleep"),
    ):
        result = runner.run(
            "mock", [], stdin_text=None, timeout_seconds=5.0, max_output_characters=1000
        )

    assert result.stdout == "hi"
    assert mock_rmtree.call_count == 5  # _CLEANUP_RETRY_ATTEMPTS, then gives up


def test_cleanup_is_still_attempted_when_the_process_itself_fails() -> None:
    """Cleanup must run even when the subprocess call raises — a failed
    execution must never leak its temp working directory."""
    runner = SubprocessRunner()

    with (
        patch("app.adapters.process_runner.shutil.which", return_value="/usr/bin/mock"),
        patch(
            "app.adapters.process_runner.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="mock", timeout=5.0),
        ),
        patch("app.adapters.process_runner.shutil.rmtree") as mock_rmtree,
        pytest.raises(AgentTimeoutError),
    ):
        runner.run("mock", [], stdin_text=None, timeout_seconds=5.0, max_output_characters=1000)

    assert mock_rmtree.call_count == 1


def test_workflow_payload_cannot_inject_executable_arguments() -> None:
    """The runner only ever receives the trusted `executable`/`arguments` a caller
    passes explicitly — there is no code path that reads workflow step input to
    build the command. This test documents that `run()`'s signature has no such
    parameter, so a workflow payload has no way to reach the command line.

    `cwd` (Stage 8C.3) does not weaken this: it is a working *directory*,
    never appended to `command`/`arguments` and never shell-interpreted --
    it flows only from `OrchestrationRequest.workspace_root`, itself
    validated server-side (`app.adapters.workspace.validate_workspace_root`
    -- absolute, must already exist, must be a directory) before it can
    reach here, never from a workflow step's own input payload.
    """
    import inspect

    signature = inspect.signature(SubprocessRunner.run)
    assert set(signature.parameters) == {
        "self",
        "executable",
        "arguments",
        "stdin_text",
        "timeout_seconds",
        "max_output_characters",
        "env_overrides",
        "cwd",
    }


def test_stderr_is_sanitized_and_bounded() -> None:
    runner = SubprocessRunner()
    long_stderr = "e" * 1000
    with (
        patch("app.adapters.process_runner.shutil.which", return_value="/usr/bin/mock"),
        patch(
            "app.adapters.process_runner.subprocess.run",
            return_value=_completed(returncode=1, stderr=long_stderr),
        ),
        pytest.raises(AgentProcessError) as excinfo,
    ):
        runner.run("mock", [], stdin_text=None, timeout_seconds=5.0, max_output_characters=10000)
    assert len(str(excinfo.value)) < len(long_stderr)
