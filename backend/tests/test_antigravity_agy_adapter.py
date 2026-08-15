"""Focused discovery, execution, and routing tests for Antigravity `agy`."""

from pathlib import Path
from unittest.mock import patch

from app.adapters.antigravity import AntigravityAdapter
from app.adapters.factory import activate_agent
from app.adapters.process_runner import ProcessResult, ProcessRunner
from app.adapters.prompt_builder import PromptBuilder
from app.adapters.types import CLIProfile, InputMode, OutputMode
from app.contracts.enums import AgentCapability, AgentStatus
from app.contracts.routing import RoutingRequest
from app.core.config import Settings
from app.engine.executor import StepExecutionRequest
from app.engine.orchestration.runtime import STATIC_AGENT_DESCRIPTORS
from app.engine.registry import ExecutorRegistry
from app.engine.routing.availability import CandidateAgent
from app.engine.routing.router import Router
from app.resilience.circuit_breaker import CircuitState
from app.services.runtime_discovery import AntigravityDiscoveryStrategy, get_discovery_strategy


class MockProcessRunner(ProcessRunner):
    """Process runner double that records the argv and working directory."""

    def __init__(self, stdout: str = "") -> None:
        self.stdout = stdout
        self.calls: list[dict[str, object]] = []

    def run(
        self,
        executable: str,
        arguments: list[str],
        *,
        stdin_text: str | None,
        timeout_seconds: float,
        max_output_characters: int,
        env_overrides: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> ProcessResult:
        self.calls.append(
            {
                "executable": executable,
                "arguments": list(arguments),
                "stdin_text": stdin_text,
                "timeout_seconds": timeout_seconds,
                "max_output_characters": max_output_characters,
                "env_overrides": env_overrides,
                "cwd": cwd,
            }
        )
        return ProcessResult(exit_code=0, stdout=self.stdout, stderr="")


def test_antigravity_runtime_identity_remains_antigravity() -> None:
    strategy = get_discovery_strategy("antigravity")
    assert strategy is not None
    assert strategy.runtime_type == "antigravity"
    assert strategy.display_name == "Google Antigravity"


def test_agy_path_candidate_is_detected() -> None:
    def fake_which(executable: str) -> str | None:
        return "C:\\tools\\agy.exe" if executable == "agy" else None

    with patch("app.services.runtime_discovery.shutil.which", side_effect=fake_which):
        info = AntigravityDiscoveryStrategy().discover(runner=MockProcessRunner("1.1.10"))

    assert info.executable_path == "C:\\tools\\agy.exe"
    assert info.product_kind == "agent_cli"
    assert info.installation_status.value == "installed"
    assert info.execution_supported is True


def test_agy_found_at_exact_localappdata_fallback(tmp_path: Path, monkeypatch: object) -> None:
    localappdata = tmp_path / "LocalAppData"
    agy_bin = localappdata / "agy" / "bin" / "agy.exe"
    agy_bin.parent.mkdir(parents=True)
    agy_bin.write_text("binary", encoding="utf-8")

    monkeypatch.setenv("LOCALAPPDATA", str(localappdata))
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("PROGRAMFILES", raising=False)
    monkeypatch.delenv("PROGRAMFILES(X86)", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)

    strategy = AntigravityDiscoveryStrategy()
    executable = strategy.find_executable()

    assert executable is not None
    assert Path(executable).resolve() == agy_bin.resolve()
    assert strategy._candidate_subpaths[0] == ("agy", "bin", "agy.exe")
    for subpath in strategy._candidate_subpaths:
        joined = "/".join(subpath).lower()
        assert "nikhi" not in joined
        assert "users" not in joined


def test_agy_preferred_over_ide_launcher(tmp_path: Path, monkeypatch: object) -> None:
    localappdata = tmp_path / "LocalAppData"
    program_files = tmp_path / "ProgramFiles"
    agy_bin = localappdata / "agy" / "bin" / "agy.exe"
    agy_bin.parent.mkdir(parents=True)
    agy_bin.write_text("agy binary", encoding="utf-8")
    ide_bin = program_files / "Antigravity IDE" / "bin" / "antigravity-ide.cmd"
    ide_bin.parent.mkdir(parents=True)
    ide_bin.write_text("ide launcher", encoding="utf-8")

    monkeypatch.setenv("LOCALAPPDATA", str(localappdata))
    monkeypatch.setenv("PROGRAMFILES", str(program_files))
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("PROGRAMFILES(X86)", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)

    info = AntigravityDiscoveryStrategy().discover()

    assert info.installation_status.value == "installed"
    assert info.product_kind == "agent_cli"
    assert info.execution_supported is True
    assert info.executable_path is not None
    assert Path(info.executable_path).resolve() == agy_bin.resolve()


def test_ide_only_state_is_installed_but_execution_unsupported(
    tmp_path: Path, monkeypatch: object
) -> None:
    program_files = tmp_path / "ProgramFiles"
    ide_bin = program_files / "Antigravity IDE" / "bin" / "antigravity-ide.cmd"
    ide_bin.parent.mkdir(parents=True)
    ide_bin.write_text("ide launcher", encoding="utf-8")

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "empty_localappdata"))
    monkeypatch.setenv("PROGRAMFILES", str(program_files))
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("PROGRAMFILES(X86)", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)

    info = AntigravityDiscoveryStrategy().discover()

    assert info.installation_status.value == "installed"
    assert info.product_kind == "ide"
    assert info.execution_supported is False
    assert "Execution adapter unavailable" in info.reason


def test_adapter_uses_exact_argv_and_workspace_cwd(tmp_path: Path) -> None:
    target_workspace = tmp_path / "my_project"
    target_workspace.mkdir()
    profile = CLIProfile(
        agent_type="antigravity",
        enabled=True,
        executable="agy.exe",
        arguments=["-p", "{prompt}"],
        input_mode=InputMode.PROMPT_ARGUMENT,
        output_mode=OutputMode.TEXT,
        timeout_seconds=30.0,
        max_output_characters=100000,
    )
    runner = MockProcessRunner(stdout="done")
    adapter = AntigravityAdapter(profile, runner, PromptBuilder(max_prompt_characters=100000))
    request = StepExecutionRequest(
        workflow_id="wf-1",
        step_id="step-1",
        step_name="Step 1",
        agent_type="antigravity",
        step_input={"goal": "Create hello.txt"},
        workflow_input={},
        previous_step_outputs={},
        workspace_root=str(target_workspace),
    )

    result = adapter.execute(request)

    assert result["content"] == "done"
    call = runner.calls[0]
    assert call["cwd"] == str(target_workspace)
    assert call["executable"] == "agy.exe"
    assert call["stdin_text"] is None
    arguments = call["arguments"]
    assert isinstance(arguments, list)
    assert len(arguments) == 2
    assert arguments[0] == "-p"
    assert "Create hello.txt" in arguments[1]


def test_activation_registers_only_executable_agy_cli(tmp_path: Path, monkeypatch: object) -> None:
    registry = ExecutorRegistry()
    settings = Settings()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "empty1"))
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("PROGRAMFILES", raising=False)
    monkeypatch.delenv("PROGRAMFILES(X86)", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)

    assert activate_agent(registry, settings, "antigravity") is False
    assert "antigravity" not in registry._executors

    program_files = tmp_path / "ProgramFiles"
    ide_bin = program_files / "Antigravity IDE" / "bin" / "antigravity-ide.cmd"
    ide_bin.parent.mkdir(parents=True)
    ide_bin.write_text("ide", encoding="utf-8")
    monkeypatch.setenv("PROGRAMFILES", str(program_files))
    assert activate_agent(registry, settings, "antigravity") is False
    assert "antigravity" not in registry._executors

    localappdata = tmp_path / "LocalAppData"
    agy_bin = localappdata / "agy" / "bin" / "agy.exe"
    agy_bin.parent.mkdir(parents=True)
    agy_bin.write_text("agy", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(localappdata))
    assert activate_agent(registry, settings, "antigravity") is True
    assert "antigravity" in registry._executors


def test_codex_and_antigravity_are_independently_router_eligible() -> None:
    candidates = [
        CandidateAgent(
            descriptor=STATIC_AGENT_DESCRIPTORS[agent_type],
            status=AgentStatus.AVAILABLE,
            circuit_state=CircuitState.CLOSED,
        )
        for agent_type in ("codex", "antigravity")
    ]
    request = RoutingRequest(
        task_type="code_generation",
        required_capabilities=[
            AgentCapability.CODE_GENERATION,
            AgentCapability.FILE_EDITING,
            AgentCapability.TEST_EXECUTION,
        ],
    )

    decision = Router().route(request, candidates)

    assert {score.agent_type for score in decision.candidates if score.eligible} == {
        "codex",
        "antigravity",
    }
    assert {decision.selected_agent_type, *decision.fallback_order} == {
        "codex",
        "antigravity",
    }
