"""Tests for `app.engine.orchestration.command_executor.SubprocessCommandExecutor`
-- the first real implementation of Stage 4E's `CommandExecutor` seam
(Stage 8C.3 P1 fix, Part 4/13/14). Real subprocess calls throughout: these
prove `shell=False`, real exit-code preservation, bounded timeout, bounded
output, and environment scoping actually hold at the OS process boundary,
not just in a mocked unit test."""

import sys

import pytest

from app.engine.orchestration.command_executor import (
    ALLOWED_EXECUTABLES,
    SubprocessCommandExecutor,
    UnapprovedCommandError,
)
from app.engine.verification.evaluators import CommandSpec


def test_allowed_executables_are_only_language_runtimes() -> None:
    assert frozenset({"node", "python"}) == ALLOWED_EXECUTABLES


def test_real_exit_code_zero_is_preserved(tmp_path) -> None:
    executor = SubprocessCommandExecutor()
    outcome = executor.run(
        CommandSpec(argv=("python", "-c", "raise SystemExit(0)"), cwd=str(tmp_path))
    )
    assert outcome.exit_code == 0
    assert outcome.timed_out is False


def test_real_nonzero_exit_code_is_preserved(tmp_path) -> None:
    executor = SubprocessCommandExecutor()
    outcome = executor.run(
        CommandSpec(argv=("python", "-c", "raise SystemExit(7)"), cwd=str(tmp_path))
    )
    assert outcome.exit_code == 7


def test_stdout_is_captured_from_real_process(tmp_path) -> None:
    executor = SubprocessCommandExecutor()
    outcome = executor.run(
        CommandSpec(argv=("python", "-c", "print('hello-from-subprocess')"), cwd=str(tmp_path))
    )
    assert "hello-from-subprocess" in outcome.stdout


def test_unapproved_executable_is_rejected(tmp_path) -> None:
    executor = SubprocessCommandExecutor()
    with pytest.raises(UnapprovedCommandError):
        executor.run(CommandSpec(argv=("bash", "-c", "echo hi"), cwd=str(tmp_path)))


def test_shell_metacharacters_in_argument_are_treated_literally(tmp_path) -> None:
    """Proof `shell=False` actually holds: a shell would interpret `;`/`&&`
    as command separators. Passed as a single argv entry, it must be
    treated as one literal, inert string argument instead."""
    executor = SubprocessCommandExecutor()
    marker = tmp_path / "should_not_exist.txt"
    payload = f"; echo pwned > {marker}"
    outcome = executor.run(
        CommandSpec(
            argv=("python", "-c", "import sys; print(sys.argv[1])", payload), cwd=str(tmp_path)
        )
    )
    assert outcome.exit_code == 0
    assert payload.strip() in outcome.stdout
    assert not marker.exists()


def test_bounded_timeout_reports_timed_out(tmp_path) -> None:
    executor = SubprocessCommandExecutor()
    outcome = executor.run(
        CommandSpec(
            argv=("python", "-c", "import time; time.sleep(5)"),
            cwd=str(tmp_path),
            timeout_seconds=0.5,
        )
    )
    assert outcome.timed_out is True
    assert outcome.exit_code != 0


def test_bounded_output_is_truncated(tmp_path) -> None:
    executor = SubprocessCommandExecutor()
    outcome = executor.run(
        CommandSpec(
            argv=("python", "-c", "print('x' * 100000)"),
            cwd=str(tmp_path),
        )
    )
    assert len(outcome.stdout) < 100000
    assert outcome.stdout.endswith("... (output truncated)")


def test_cwd_must_exist(tmp_path) -> None:
    executor = SubprocessCommandExecutor()
    missing = tmp_path / "nope"
    with pytest.raises(ValueError, match="cwd"):
        executor.run(CommandSpec(argv=("python", "--version"), cwd=str(missing)))


def test_environment_never_passes_through_arbitrary_secrets(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("KEYSTONE_TEST_FAKE_SECRET", "super-secret-value")
    executor = SubprocessCommandExecutor()
    outcome = executor.run(
        CommandSpec(
            argv=(
                "python",
                "-c",
                "import os; print(os.environ.get('KEYSTONE_TEST_FAKE_SECRET', '<absent>'))",
            ),
            cwd=str(tmp_path),
        )
    )
    assert "super-secret-value" not in outcome.stdout
    assert "<absent>" in outcome.stdout


def test_real_python_is_actually_invoked_not_faked(tmp_path) -> None:
    executor = SubprocessCommandExecutor()
    outcome = executor.run(
        CommandSpec(
            argv=("python", "-c", "import sys; print(sys.version_info[0])"),
            cwd=str(tmp_path),
        )
    )
    assert outcome.stdout.strip() == str(sys.version_info[0])
