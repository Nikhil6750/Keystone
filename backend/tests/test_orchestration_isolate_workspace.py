"""Integration tests proving `OrchestrationRequest.isolate_workspace` is a
real, working capability end-to-end through `EndToEndOrchestrationService`,
not just a flag the isolation manager's own unit tests exercise in
isolation. Mirrors `test_orchestration_workspace_evidence.py`'s fixtures
(`_request`/`_service`/`WorkspaceWritingExecutor`), with a real git
repository as `workspace_root` instead of a plain directory."""

import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from app.contracts.enums import AgentCapability
from app.engine.executor import StepExecutionRequest
from app.engine.orchestration.models import OrchestrationOutcome, OrchestrationRequest
from app.engine.orchestration.runtime import StaticCandidateProvider
from app.engine.orchestration.service import EndToEndOrchestrationService
from app.engine.registry import ExecutorRegistry
from app.engine.verification.recovery import RecoveryPolicy
from app.resilience.circuit_breaker import CircuitBreakerRegistry
from app.resilience.retry import RetryPolicy
from tests.support.orchestration_fakes import build_candidate

_GOAL = "Write a test for add function"  # -> deterministic test_creation_medium template


def _git(args: list[str], *, cwd: Path) -> None:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30, shell=False
    )
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"


def _init_repo(path: Path) -> None:
    _git(["init", "-b", "main"], cwd=path)
    _git(["config", "user.email", "test@example.com"], cwd=path)
    _git(["config", "user.name", "Keystone Test"], cwd=path)
    (path / "README.md").write_text("initial\n", encoding="utf-8")
    _git(["add", "README.md"], cwd=path)
    _git(["commit", "-m", "initial commit"], cwd=path)


@dataclass
class WorkspaceWritingExecutor:
    """Writes real files into `request.workspace_root`, exactly like
    `test_orchestration_workspace_evidence.py`'s own fixture."""

    calls: list[StepExecutionRequest] = field(default_factory=list)

    def execute(self, request: StepExecutionRequest) -> dict[str, object]:
        self.calls.append(request)
        assert request.workspace_root is not None
        root = Path(request.workspace_root)
        (root / "add.js").write_text(
            "function add(a, b) { return a + b; }\nmodule.exports = { add };\n", encoding="utf-8"
        )
        (root / "add.test.js").write_text(
            "const test = require('node:test');\n"
            "const assert = require('node:assert');\n"
            "const { add } = require('./add.js');\n"
            "test('adds', () => { assert.strictEqual(add(2, 3), 5); });\n",
            encoding="utf-8",
        )
        return {
            "agent_type": "demo",
            "content": "done",
            "metadata": {"execution_mode": "local_cli"},
        }


def _request(workspace_root: str, **overrides: object) -> OrchestrationRequest:
    base: dict[str, object] = {
        "request_id": f"req-{uuid.uuid4().hex[:8]}",
        "goal": _GOAL,
        "available_agent_types": ["demo"],
        "available_capabilities": [AgentCapability.CODE_GENERATION],
        "workspace_root": workspace_root,
    }
    base.update(overrides)
    return OrchestrationRequest.model_validate(base)


def _service(db: Session, *, executor: WorkspaceWritingExecutor) -> EndToEndOrchestrationService:
    registry = ExecutorRegistry()
    registry.register("demo", executor)
    return EndToEndOrchestrationService(
        db=db,
        registry=registry,
        candidate_provider=StaticCandidateProvider(agents=(build_candidate("demo"),)),
        circuit_breakers=CircuitBreakerRegistry(failure_threshold=3, recovery_timeout_seconds=30.0),
        retry_policy=RetryPolicy(base_delay_seconds=0.01, max_delay_seconds=0.05),
        recovery_policy=RecoveryPolicy(max_attempts=1, allow_reroute=False, allow_retry_same=False),
    )


async def test_isolated_run_merges_real_files_back_into_the_target_repo(
    db_session: Session, tmp_path: Path
) -> None:
    _init_repo(tmp_path)
    executor = WorkspaceWritingExecutor()
    service = _service(db_session, executor=executor)

    result = await service.orchestrate(_request(str(tmp_path), isolate_workspace=True))

    assert result.outcome == OrchestrationOutcome.VERIFIED_SUCCESS
    # Merged back into the *original* checkout, not left stranded in a
    # worktree the caller never sees.
    assert (tmp_path / "add.js").exists()
    assert (tmp_path / "add.test.js").exists()
    # The executor itself never wrote to the original tmp_path directly --
    # proof the isolation actually happened, not merely that integration
    # worked despite it.
    assert all(call.workspace_root != str(tmp_path) for call in executor.calls)

    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=tmp_path, capture_output=True, text=True, timeout=30
    ).stdout
    assert "merge(keystone)" in log

    worktree_list = subprocess.run(
        ["git", "worktree", "list"], cwd=tmp_path, capture_output=True, text=True, timeout=30
    ).stdout
    assert worktree_list.strip().count("\n") == 0  # only the main checkout remains
    branch_list = subprocess.run(
        ["git", "branch"], cwd=tmp_path, capture_output=True, text=True, timeout=30
    ).stdout
    assert "keystone/run-" not in branch_list


async def test_default_behavior_is_unchanged_when_isolate_workspace_is_unset(
    db_session: Session, tmp_path: Path
) -> None:
    _init_repo(tmp_path)
    executor = WorkspaceWritingExecutor()
    service = _service(db_session, executor=executor)

    result = await service.orchestrate(_request(str(tmp_path)))

    assert result.outcome == OrchestrationOutcome.VERIFIED_SUCCESS
    # Unmodified default path: the executor writes straight into the real
    # workspace_root, no worktree ever created.
    assert all(call.workspace_root == str(tmp_path) for call in executor.calls)
    worktree_list = subprocess.run(
        ["git", "worktree", "list"], cwd=tmp_path, capture_output=True, text=True, timeout=30
    ).stdout
    assert worktree_list.strip().count("\n") == 0
