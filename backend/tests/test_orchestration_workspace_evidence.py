"""Stage 8C.3 P1 fix -- integration tests proving the real gap is closed:
a step that genuinely wrote correct, working files into a real, persistent
workspace and passed its own real test suite must reach
`VerificationStatus.PASSED`/`OrchestrationOutcome.VERIFIED_SUCCESS` with
`recovery_used is False` on the first attempt, through the actual
end-to-end pipeline (real `Planner`, real `Router`, real `WorkflowEngine`,
real Stage 4E verifier, real `WorkspaceEvidenceCollector` running real
`node`/`python` subprocesses against a real `tmp_path` workspace) -- never
by weakening verification, and a genuinely broken/failing result must still
resolve to `VerificationStatus.FAILED`, never `VERIFIED_SUCCESS`.

Uses the exact same fixtures/helpers as `test_orchestration_service.py`
(`_service`/`_request`/`db_session`/`build_candidate`) -- the only new
ingredient is `workspace_root` and an executor that performs real file
writes instead of returning a pre-fabricated evidence dict, which is
exactly the gap this fix closes."""

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from app.contracts.enums import AgentCapability
from app.engine.adaptive_retrieval.feedback import InMemoryRetrievalFeedbackRepository
from app.engine.executor import StepExecutionRequest
from app.engine.orchestration.models import OrchestrationOutcome, OrchestrationRequest
from app.engine.orchestration.runtime import StaticCandidateProvider
from app.engine.orchestration.service import EndToEndOrchestrationService
from app.engine.registry import ExecutorRegistry
from app.engine.verification.recovery import RecoveryPolicy
from app.models.enums import WorkflowStatus
from app.resilience.circuit_breaker import CircuitBreakerRegistry
from app.resilience.retry import RetryPolicy
from tests.support.orchestration_fakes import build_candidate

_GOAL = "Write a test for add function"  # -> deterministic test_creation_medium template


@dataclass
class WorkspaceWritingExecutor:
    """Simulates a real local-CLI agent (any provider): writes real files
    into `request.workspace_root` and returns only free-text `content` --
    no `exit_code`/`tests_total`/evidence keys at all, exactly like the
    real `LocalCLIAdapter`/`ClaudeCodeAdapter` output shape this fix
    targets. `content` deliberately makes a confident prose claim
    ("All tests passed! 32/32") that must never itself be treated as
    evidence -- only the real files/real test run matter."""

    passing: bool
    calls: list[StepExecutionRequest] = field(default_factory=list)

    def execute(self, request: StepExecutionRequest) -> dict[str, object]:
        self.calls.append(request)
        assert request.workspace_root is not None
        root = Path(request.workspace_root)
        add_js = root / "add.js"
        if not add_js.exists():
            operator = "+" if self.passing else "-"
            add_js.write_text(
                f"function add(a, b) {{ return a {operator} b; }}\nmodule.exports = {{ add }};\n",
                encoding="utf-8",
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
            "content": "All tests passed! 32/32. Everything works.",
            "metadata": {"execution_mode": "local_cli"},
        }


def _request(workspace_root: str, **overrides: object) -> OrchestrationRequest:
    import uuid

    base: dict[str, object] = {
        "request_id": f"req-{uuid.uuid4().hex[:8]}",
        "goal": _GOAL,
        "available_agent_types": ["demo"],
        "available_capabilities": [AgentCapability.CODE_GENERATION],
        "workspace_root": workspace_root,
    }
    base.update(overrides)
    return OrchestrationRequest.model_validate(base)


def _service(
    db: Session, *, executor: WorkspaceWritingExecutor, **kwargs: object
) -> EndToEndOrchestrationService:
    registry = ExecutorRegistry()
    registry.register("demo", executor)
    return EndToEndOrchestrationService(
        db=db,
        registry=registry,
        candidate_provider=StaticCandidateProvider(agents=(build_candidate("demo"),)),
        circuit_breakers=CircuitBreakerRegistry(failure_threshold=3, recovery_timeout_seconds=30.0),
        retry_policy=RetryPolicy(base_delay_seconds=0.01, max_delay_seconds=0.05),
        **kwargs,
    )


async def test_real_workspace_success_reaches_verified_success_first_attempt(
    db_session: Session, tmp_path: Path
) -> None:
    executor = WorkspaceWritingExecutor(passing=True)
    service = _service(db_session, executor=executor)

    result = await service.orchestrate(_request(str(tmp_path)))

    assert result.final_workflow_state == WorkflowStatus.SUCCEEDED
    assert result.verification_status is not None
    assert result.verification_status.value == "passed"
    assert result.outcome == OrchestrationOutcome.VERIFIED_SUCCESS
    assert result.recovery_used is False
    # Real files genuinely exist -- not merely claimed by `content`.
    assert (tmp_path / "add.js").exists()
    assert (tmp_path / "add.test.js").exists()


async def test_real_workspace_genuine_test_failure_never_becomes_verified_success(
    db_session: Session, tmp_path: Path
) -> None:
    executor = WorkspaceWritingExecutor(passing=False)
    service = _service(
        db_session,
        executor=executor,
        recovery_policy=RecoveryPolicy(max_attempts=1, allow_reroute=False, allow_retry_same=False),
    )

    result = await service.orchestrate(_request(str(tmp_path)))

    assert result.outcome != OrchestrationOutcome.VERIFIED_SUCCESS
    assert result.verification_status is not None
    assert result.verification_status.value == "failed"


async def test_model_prose_claiming_success_is_never_treated_as_evidence(
    db_session: Session, tmp_path: Path
) -> None:
    """`WorkspaceWritingExecutor.execute` always returns the same confident
    prose ("All tests passed! ... Everything works.") regardless of
    `passing` -- proving the real, opposite-of-the-prose outcome (FAILED)
    still wins when the real test genuinely fails, i.e. nothing in the
    pipeline ever parses `content` as evidence."""
    executor = WorkspaceWritingExecutor(passing=False)
    service = _service(
        db_session,
        executor=executor,
        recovery_policy=RecoveryPolicy(max_attempts=1, allow_reroute=False, allow_retry_same=False),
    )

    result = await service.orchestrate(_request(str(tmp_path)))

    assert executor.calls  # the confident-prose executor really did run
    assert result.outcome != OrchestrationOutcome.VERIFIED_SUCCESS
    assert result.verification_status is not None and result.verification_status.value == "failed"


async def test_retrieval_feedback_and_learning_reflect_real_passed_status(
    db_session: Session, tmp_path: Path
) -> None:
    executor = WorkspaceWritingExecutor(passing=True)
    repo = InMemoryRetrievalFeedbackRepository()
    service = _service(db_session, executor=executor, retrieval_feedback_repository=repo)

    result = await service.orchestrate(_request(str(tmp_path)))

    assert result.outcome == OrchestrationOutcome.VERIFIED_SUCCESS
    stored_events = [
        service._learning_persistence.get_learning_event(db_session, event_id)  # noqa: SLF001
        for event_id in result.learning_event_ids
    ]
    verified_statuses = [
        event.verification_status.value
        for event in stored_events
        if event is not None and event.verification_status is not None
    ]
    assert verified_statuses
    assert all(status == "passed" for status in verified_statuses)


async def test_workspace_root_is_preserved_into_recovery_cycle(
    db_session: Session, tmp_path: Path
) -> None:
    """Even when recovery runs (here, forced by a first-attempt failure),
    every executor call -- main phase and recovery cycle alike -- must see
    the exact same real `workspace_root`, never an ephemeral substitute."""
    executor = WorkspaceWritingExecutor(passing=False)
    service = _service(
        db_session,
        executor=executor,
        recovery_policy=RecoveryPolicy(max_attempts=2, allow_reroute=False, allow_retry_same=True),
    )

    await service.orchestrate(_request(str(tmp_path)))

    assert len(executor.calls) >= 2
    assert all(call.workspace_root == str(tmp_path) for call in executor.calls)
