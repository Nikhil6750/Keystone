"""Tests for the shared connection-verification behavior on `LocalCLIAdapter`
(detect/read_version/verify_connection) and the workspace-root validator.
All process execution is faked — no real subprocess is ever launched here.
"""

from unittest.mock import patch

import pytest

from app.adapters.connection import AgentConnectionCache, ConnectionStatus, InstallationStatus
from app.adapters.gemini import GeminiAdapter
from app.adapters.process_runner import ProcessResult
from app.adapters.prompt_builder import PromptBuilder
from app.adapters.types import create_cli_profile
from app.adapters.workspace import WorkspaceValidationError, resolve_workspace_directory
from tests.support.fakes import FakeProcessRunner


def _profile(**overrides: object) -> object:
    defaults: dict[str, object] = dict(
        agent_type="gemini",
        enabled=True,
        executable="mock",
        arguments=["-p", "{prompt}"],
        input_mode="prompt_argument",
        output_mode="json",
        timeout_seconds=5.0,
        max_output_characters=1000,
    )
    defaults.update(overrides)
    return create_cli_profile(**defaults)  # type: ignore[arg-type]


def test_detect_reports_installed_when_executable_resolves() -> None:
    profile = _profile()
    adapter = GeminiAdapter(profile, FakeProcessRunner(), PromptBuilder(max_prompt_characters=1000))

    with patch("app.adapters.local_cli.shutil.which", return_value="/usr/bin/mock"):
        assert adapter.detect() is InstallationStatus.INSTALLED


def test_detect_reports_not_installed_when_executable_is_missing() -> None:
    profile = _profile()
    adapter = GeminiAdapter(profile, FakeProcessRunner(), PromptBuilder(max_prompt_characters=1000))

    with patch("app.adapters.local_cli.shutil.which", return_value=None):
        assert adapter.detect() is InstallationStatus.NOT_INSTALLED


def test_read_version_parses_first_stdout_line() -> None:
    profile = _profile()
    runner = FakeProcessRunner(result=ProcessResult(exit_code=0, stdout="1.2.3\n", stderr=""))
    adapter = GeminiAdapter(profile, runner, PromptBuilder(max_prompt_characters=1000))

    assert adapter.read_version() == "1.2.3"


def test_read_version_returns_none_on_failure_rather_than_raising() -> None:
    from app.adapters.exceptions import AgentUnavailableError

    profile = _profile()
    runner = FakeProcessRunner(error=AgentUnavailableError("not found"))
    adapter = GeminiAdapter(profile, runner, PromptBuilder(max_prompt_characters=1000))

    assert adapter.read_version() is None


def test_verify_connection_succeeds_when_token_present_in_response() -> None:
    profile = _profile()
    runner = FakeProcessRunner()

    def _dynamic_result(executable: str, arguments: list[str], **_: object) -> ProcessResult:
        prompt = arguments[-1]
        token = prompt.split("Reply with exactly ")[1].split(".")[0]
        return ProcessResult(exit_code=0, stdout=f'{{"result": "{token}"}}', stderr="")

    runner.run = _dynamic_result  # type: ignore[method-assign]
    adapter = GeminiAdapter(profile, runner, PromptBuilder(max_prompt_characters=1000))

    status, reason = adapter.verify_connection()

    assert status is ConnectionStatus.CONNECTED
    assert reason


def test_verify_connection_fails_when_token_absent() -> None:
    profile = _profile()
    runner = FakeProcessRunner(
        result=ProcessResult(exit_code=0, stdout='{"result": "something else"}', stderr="")
    )
    adapter = GeminiAdapter(profile, runner, PromptBuilder(max_prompt_characters=1000))

    status, reason = adapter.verify_connection()

    assert status is ConnectionStatus.VERIFICATION_FAILED
    assert reason


def test_verify_connection_fails_safely_on_process_error() -> None:
    from app.adapters.exceptions import AgentProcessError

    profile = _profile()
    runner = FakeProcessRunner(error=AgentProcessError("boom"))
    adapter = GeminiAdapter(profile, runner, PromptBuilder(max_prompt_characters=1000))

    status, _reason = adapter.verify_connection()

    assert status is ConnectionStatus.VERIFICATION_FAILED


class TestAgentConnectionCache:
    def test_cache_returns_none_before_any_verification(self) -> None:
        cache = AgentConnectionCache(cache_seconds=60.0)
        assert cache.get("claude_code") is None

    def test_duplicate_verification_is_rejected_while_in_progress(self) -> None:
        cache = AgentConnectionCache(cache_seconds=60.0)
        assert cache.try_begin_verification("claude_code") is True
        assert cache.try_begin_verification("claude_code") is False
        cache.end_verification("claude_code")
        assert cache.try_begin_verification("claude_code") is True


class TestWorkspaceValidation:
    def test_default_working_directory_is_the_workspace_root(self, tmp_path: object) -> None:
        root = str(tmp_path)
        resolved = resolve_workspace_directory(None, root)
        assert str(resolved) == str(resolved.resolve())

    def test_a_subdirectory_of_the_root_is_accepted(self, tmp_path: object) -> None:
        import pathlib

        root = pathlib.Path(str(tmp_path))
        sub = root / "child"
        sub.mkdir()

        resolved = resolve_workspace_directory(str(sub), str(root))

        assert resolved == sub.resolve()

    def test_path_traversal_outside_the_root_is_rejected(self, tmp_path: object) -> None:
        import pathlib

        root = pathlib.Path(str(tmp_path)) / "workspace"
        root.mkdir()

        with pytest.raises(WorkspaceValidationError):
            resolve_workspace_directory(str(root / ".." / ".." / "etc"), str(root))

    def test_an_unrelated_absolute_path_is_rejected(self, tmp_path: object) -> None:
        import pathlib

        root = pathlib.Path(str(tmp_path)) / "workspace"
        root.mkdir()
        other = pathlib.Path(str(tmp_path)) / "elsewhere"
        other.mkdir()

        with pytest.raises(WorkspaceValidationError):
            resolve_workspace_directory(str(other), str(root))
