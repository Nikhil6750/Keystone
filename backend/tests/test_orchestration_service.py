"""Focused tests for `app.engine.orchestration.service.EndToEndOrchestrationService`,
covering the Stage 8C.1 required scenarios (Part 10).
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.contracts.enums import AgentCapability, BenchmarkEvaluatorType
from app.contracts.planning import TaskSpec, WorkflowPlan
from app.contracts.routing import RoutingRequest
from app.contracts.verification import VerificationResult, VerificationStatus
from app.engine.adaptive_retrieval.feedback import InMemoryRetrievalFeedbackRepository
from app.engine.adaptive_retrieval.policy import AdaptiveRetrievalPolicy
from app.engine.adaptive_retrieval.reranking import AdaptiveRetriever
from app.engine.executor import StepExecutionRequest
from app.engine.knowledge.index import KnowledgeIndex
from app.engine.knowledge.models import KnowledgeChunk, KnowledgeDocument
from app.engine.manager.errors import ManagerUnavailableError
from app.engine.manager.fake import FakeManagerModel
from app.engine.manager.models import ManagerResponse, ManagerTaskProposal
from app.engine.orchestration.models import OrchestrationOutcome, OrchestrationRequest
from app.engine.orchestration.runtime import StaticCandidateProvider
from app.engine.orchestration.service import EndToEndOrchestrationService, _RoutingContext
from app.engine.registry import ExecutorRegistry
from app.engine.routing.availability import CandidateAgent
from app.engine.verification.recovery import RecoveryAction, RecoveryDecision, RecoveryPolicy
from app.models.enums import WorkflowStatus
from app.persistence.service import build_event_id
from app.resilience.circuit_breaker import CircuitBreakerRegistry, CircuitState
from tests.support.executors import FailingExecutor, RecordingExecutor
from tests.support.orchestration_fakes import RICH_SUCCESS_OUTPUT, build_candidate


def _request(**overrides: object) -> OrchestrationRequest:
    base: dict[str, object] = {
        "request_id": f"req-{uuid.uuid4().hex[:8]}",
        "goal": "Implement user authentication with tests",
        "available_agent_types": ["demo"],
        "available_capabilities": [AgentCapability.CODE_GENERATION],
    }
    base.update(overrides)
    return OrchestrationRequest.model_validate(base)


def _service(
    db: Session,
    *,
    registry: ExecutorRegistry,
    candidates: list[CandidateAgent],
    **kwargs: object,
) -> EndToEndOrchestrationService:
    return EndToEndOrchestrationService(
        db=db,
        registry=registry,
        candidate_provider=StaticCandidateProvider(agents=tuple(candidates)),
        **kwargs,
    )


def _registry_with_demo(output: dict | None = None) -> tuple[ExecutorRegistry, RecordingExecutor]:
    registry = ExecutorRegistry()
    executor = RecordingExecutor(output=dict(output or RICH_SUCCESS_OUTPUT))
    registry.register("demo", executor)
    return registry, executor


def _knowledge_index_with_matching_doc() -> KnowledgeIndex:
    index = KnowledgeIndex()
    content = "Implement user authentication with tests using JWT tokens"
    doc = KnowledgeDocument(
        document_id="doc-1", source_id="vault", title="Auth notes", content=content
    )
    chunk = KnowledgeChunk(
        chunk_id="chunk-1", document_id="doc-1", source_id="vault", content=content, ordinal=0
    )
    index.upsert_document(doc, [chunk])
    return index


# --- 1/10. Simple happy path / verified success -----------------------------


async def test_happy_path_verified_success(db_session: Session) -> None:
    registry, executor = _registry_with_demo()
    service = _service(db_session, registry=registry, candidates=[build_candidate("demo")])
    result = await service.orchestrate(_request())

    assert result.outcome == OrchestrationOutcome.VERIFIED_SUCCESS
    assert result.final_workflow_state == WorkflowStatus.SUCCEEDED
    assert result.verification_status is not None
    assert result.verification_status.value == "passed"
    assert len(executor.calls) == result.task_count
    assert result.learning_event_ids
    assert result.recovery_used is False


# --- 2. Manager success -----------------------------------------------------


async def test_manager_success_used_and_influences_routing(db_session: Session) -> None:
    registry = ExecutorRegistry()
    registry.register("demo", RecordingExecutor(output=RICH_SUCCESS_OUTPUT))
    registry.register("claude_code", RecordingExecutor(output=RICH_SUCCESS_OUTPUT))
    candidates = [build_candidate("demo"), build_candidate("claude_code")]

    request = _request(available_agent_types=["demo", "claude_code"])
    manager_response = ManagerResponse(
        request_id=request.request_id,
        provider_identifier="fake-manager",
        task_proposals=[
            ManagerTaskProposal(key="t1", description="d", preferred_agent_types=["claude_code"])
        ],
    )
    fake_model = FakeManagerModel(response=manager_response)
    service = _service(
        db_session, registry=registry, candidates=candidates, manager_model=fake_model
    )
    result = await service.orchestrate(request)

    assert result.manager_used is True
    assert result.manager_fallback_used is False
    assert result.manager_proposal_validated is True
    assert result.manager_provider_identifier == "fake-manager"
    assert result.selected_agent_types == ("claude_code",)
    assert result.outcome == OrchestrationOutcome.VERIFIED_SUCCESS


# --- 3. Manager failure -> deterministic fallback ---------------------------


async def test_manager_failure_falls_back_to_deterministic_planner(db_session: Session) -> None:
    registry, _ = _registry_with_demo()
    fake_model = FakeManagerModel(exception=ManagerUnavailableError("provider down"))
    service = _service(
        db_session,
        registry=registry,
        candidates=[build_candidate("demo")],
        manager_model=fake_model,
    )
    result = await service.orchestrate(_request())

    assert result.manager_used is True
    assert result.manager_fallback_used is True
    assert result.manager_proposal_validated is False
    assert result.outcome == OrchestrationOutcome.VERIFIED_SUCCESS
    assert len(fake_model.calls) == 1


# --- 4. Invalid/rejected manager proposal -> deterministic fallback --------


async def test_rejected_manager_proposal_falls_back(db_session: Session) -> None:
    registry, _ = _registry_with_demo()
    request = _request(available_agent_types=["demo"])
    manager_response = ManagerResponse(
        request_id=request.request_id,
        task_proposals=[
            ManagerTaskProposal(
                key="t1", description="d", preferred_agent_types=["totally_unknown"]
            )
        ],
    )
    fake_model = FakeManagerModel(response=manager_response)
    service = _service(
        db_session,
        registry=registry,
        candidates=[build_candidate("demo")],
        manager_model=fake_model,
    )
    result = await service.orchestrate(request)

    assert result.manager_proposal_validated is False
    assert result.manager_fallback_used is True
    assert "unknown_preferred_agent_type" in result.issue_codes
    assert result.outcome == OrchestrationOutcome.VERIFIED_SUCCESS


# --- 5/25. Router authority: manager preference cannot select an ineligible agent --


async def test_manager_preference_cannot_select_ineligible_agent(db_session: Session) -> None:
    registry, _ = _registry_with_demo()
    registry.register(
        "banned_agent", RecordingExecutor(output=RICH_SUCCESS_OUTPUT)
    )
    candidates = [build_candidate("demo"), build_candidate("banned_agent")]

    request = _request(
        available_agent_types=["demo", "banned_agent"],
        routing_constraints={"excluded_agent_types": ["banned_agent"]},
    )
    manager_response = ManagerResponse(
        request_id=request.request_id,
        task_proposals=[
            ManagerTaskProposal(key="t1", description="d", preferred_agent_types=["banned_agent"])
        ],
    )
    fake_model = FakeManagerModel(response=manager_response)
    service = _service(
        db_session, registry=registry, candidates=candidates, manager_model=fake_model
    )
    result = await service.orchestrate(request)

    assert "banned_agent" not in result.selected_agent_types
    assert result.outcome == OrchestrationOutcome.VERIFIED_SUCCESS


# --- 6. No eligible route ----------------------------------------------------


async def test_no_eligible_route_bounded_failure(db_session: Session) -> None:
    registry, _ = _registry_with_demo()
    narrow_candidate = build_candidate("demo", capabilities=[])  # satisfies no capability
    service = _service(db_session, registry=registry, candidates=[narrow_candidate])
    result = await service.orchestrate(_request())

    assert result.outcome == OrchestrationOutcome.NO_ELIGIBLE_ROUTE
    assert result.workflow_id is None
    assert result.final_workflow_state is None


# --- 7. Knowledge empty / unavailable ---------------------------------------


async def test_knowledge_unavailable_orchestration_still_continues(db_session: Session) -> None:
    registry, _ = _registry_with_demo()
    service = _service(
        db_session, registry=registry, candidates=[build_candidate("demo")], knowledge_index=None
    )
    result = await service.orchestrate(_request())

    assert result.knowledge_result_count == 0
    assert result.outcome == OrchestrationOutcome.VERIFIED_SUCCESS


async def test_knowledge_index_with_no_matches_continues(db_session: Session) -> None:
    registry, _ = _registry_with_demo()
    empty_index = KnowledgeIndex()
    service = _service(
        db_session,
        registry=registry,
        candidates=[build_candidate("demo")],
        knowledge_index=empty_index,
    )
    result = await service.orchestrate(_request())

    assert result.knowledge_result_count == 0
    assert result.outcome == OrchestrationOutcome.VERIFIED_SUCCESS


# --- 8/28. Adaptive retrieval reranks only within Stage 6 candidates -------


async def test_adaptive_retrieval_used_flag_reflects_policy(db_session: Session) -> None:
    registry, _ = _registry_with_demo()
    index = _knowledge_index_with_matching_doc()
    retriever = AdaptiveRetriever(policy=AdaptiveRetrievalPolicy(enabled=True))
    service = _service(
        db_session,
        registry=registry,
        candidates=[build_candidate("demo")],
        knowledge_index=index,
        adaptive_retriever=retriever,
    )
    result = await service.orchestrate(_request())

    assert result.adaptive_retrieval_used is True
    assert result.knowledge_result_count == 1  # never more than Stage 6 base search returned


async def test_adaptive_retrieval_disabled_policy_reports_unused(db_session: Session) -> None:
    registry, _ = _registry_with_demo()
    index = _knowledge_index_with_matching_doc()
    retriever = AdaptiveRetriever(policy=AdaptiveRetrievalPolicy(enabled=False))
    service = _service(
        db_session,
        registry=registry,
        candidates=[build_candidate("demo")],
        knowledge_index=index,
        adaptive_retriever=retriever,
    )
    result = await service.orchestrate(_request())
    assert result.adaptive_retrieval_used is False


# --- 9/18/26. Retrieval feedback correctness --------------------------------


async def test_retrieval_positive_feedback_only_after_verified_success(db_session: Session) -> None:
    registry, _ = _registry_with_demo()
    index = _knowledge_index_with_matching_doc()
    repo = InMemoryRetrievalFeedbackRepository()
    service = _service(
        db_session,
        registry=registry,
        candidates=[build_candidate("demo")],
        knowledge_index=index,
        retrieval_feedback_repository=repo,
    )
    result = await service.orchestrate(_request())

    assert result.retrieval_feedback_recorded is True
    records = repo.all()
    assert len(records) == 1
    assert records[0].is_verified_success is True
    assert records[0].verification_status.value == "passed"
    assert records[0].chunk_content_hashes == () or all(
        h for h in records[0].chunk_content_hashes
    )  # never fabricated blank hashes


async def test_retrieval_feedback_not_positive_when_verification_fails(db_session: Session) -> None:
    registry, _ = _registry_with_demo(output={"output": "nope"})  # insufficient evidence
    index = _knowledge_index_with_matching_doc()
    repo = InMemoryRetrievalFeedbackRepository()
    service = _service(
        db_session,
        registry=registry,
        candidates=[build_candidate("demo")],
        knowledge_index=index,
        retrieval_feedback_repository=repo,
        recovery_policy=RecoveryPolicy(max_attempts=1, allow_reroute=False, allow_retry_same=False),
    )
    result = await service.orchestrate(_request())

    assert result.outcome != OrchestrationOutcome.VERIFIED_SUCCESS
    records = repo.all()
    assert len(records) == 1
    assert records[0].is_verified_success is False


# --- 11. Execution success but verification fail must not be verified success --


async def test_execution_success_but_verification_fail_not_verified_success(
    db_session: Session,
) -> None:
    registry, _ = _registry_with_demo(output={"output": "insufficient"})
    service = _service(
        db_session,
        registry=registry,
        candidates=[build_candidate("demo")],
        recovery_policy=RecoveryPolicy(max_attempts=1, allow_reroute=False, allow_retry_same=False),
    )
    result = await service.orchestrate(_request())

    assert result.final_workflow_state == WorkflowStatus.SUCCEEDED  # execution itself succeeded
    assert result.outcome != OrchestrationOutcome.VERIFIED_SUCCESS
    assert result.verification_status is not None
    assert result.verification_status.value != "passed"


# --- 12/13. Verification failure -> bounded recovery, then exhaustion ------


async def test_verification_failure_triggers_bounded_recovery_then_exhausts(
    db_session: Session,
) -> None:
    registry, _ = _registry_with_demo(output={"output": "insufficient"})
    service = _service(
        db_session,
        registry=registry,
        candidates=[build_candidate("demo")],
        recovery_policy=RecoveryPolicy(max_attempts=2, allow_reroute=False, allow_retry_same=True),
    )
    result = await service.orchestrate(_request())

    assert result.recovery_used is True
    assert result.outcome == OrchestrationOutcome.RECOVERY_EXHAUSTED
    assert result.recovery_action == RecoveryAction.FAIL


# --- 14. Runtime (execution) failure -----------------------------------------


async def test_runtime_failure_produces_correct_outcome(db_session: Session) -> None:
    registry = ExecutorRegistry()
    registry.register("demo", FailingExecutor())
    service = _service(db_session, registry=registry, candidates=[build_candidate("demo")])
    result = await service.orchestrate(_request())

    assert result.outcome == OrchestrationOutcome.RUNTIME_FAILURE
    assert result.final_workflow_state == WorkflowStatus.FAILED


# --- Regression: circuit breaker opening during recovery is a safe stop, ----
# --- never an unhandled exception (Stage 8C.3 usability hardening) ----------


async def test_run_recovery_cycle_returns_none_on_circuit_breaker_open_not_a_crash(
    db_session: Session,
) -> None:
    """Directly exercises `_run_recovery_cycle` with the breaker for its
    target agent type already open (e.g. tripped moments earlier by a
    different task, or a previous orchestration sharing the same
    process-wide `CircuitBreakerRegistry`): `engine.execute_workflow()`'s
    very first `before_call()` check raises `CircuitBreakerOpenError`
    before the executor is ever invoked. Previously this propagated
    uncaught out of `_run_recovery_cycle`, reported as a bare
    "CircuitBreakerOpenError: an unexpected internal error occurred"
    instead of the same bounded `None` ("cannot recover right now")
    return every other cause already produces here (see `reroute()`
    finding no eligible candidate, just above)."""

    class _NeverCalledExecutor:
        def execute(self, request: StepExecutionRequest) -> dict[str, Any]:
            raise AssertionError("must never be called -- the breaker is already open")

    registry = ExecutorRegistry()
    registry.register("demo", _NeverCalledExecutor())
    breakers = CircuitBreakerRegistry(failure_threshold=1, recovery_timeout_seconds=999)
    breakers.get_or_create("demo").record_failure()
    assert breakers.get_or_create("demo").snapshot().state == CircuitState.OPEN

    service = _service(
        db_session,
        registry=registry,
        candidates=[build_candidate("demo")],
        circuit_breakers=breakers,
    )

    task = TaskSpec(key="t1", name="task one", task_type="code_generation")
    plan = WorkflowPlan(
        plan_id="plan-regress-1", goal="goal", tasks=[task], created_at=datetime.now(UTC)
    )
    step_id = "step-1"
    results = {
        step_id: VerificationResult(
            verification_id="v1",
            workflow_id="wf-1",
            step_id=step_id,
            status=VerificationStatus.FAILED,
            evaluator_type=BenchmarkEvaluatorType.UNIT_TEST,
            failure_reason="insufficient",
            created_at=datetime.now(UTC),
        )
    }
    routing_context_by_task_key = {
        "t1": _RoutingContext(
            request=RoutingRequest(task_type="code_generation"),
            candidates=[build_candidate("demo")],
        )
    }
    decision = RecoveryDecision(
        action=RecoveryAction.RETRY_SAME,
        reason="verification failed",
        attempt_number=1,
        verification_status=VerificationStatus.FAILED,
    )

    # Must not raise -- returns None, exactly like every other "cannot
    # recover right now" cause this method already handles.
    cycle = service._run_recovery_cycle(  # noqa: SLF001 - intentional white-box test
        plan,
        {step_id: task},
        results,
        {"t1": "demo"},
        routing_context_by_task_key,
        decision,
        attempt_number=1,
    )
    assert cycle is None


# --- 15. Timeout classification ----------------------------------------------


async def test_timeout_classified_as_runtime_failure(db_session: Session) -> None:
    registry = ExecutorRegistry()
    registry.register("demo", FailingExecutor(error_type="AGENT_TIMEOUT"))
    service = _service(db_session, registry=registry, candidates=[build_candidate("demo")])
    result = await service.orchestrate(_request())

    assert result.outcome == OrchestrationOutcome.RUNTIME_FAILURE
    assert result.final_workflow_state == WorkflowStatus.FAILED


# --- 16. Cancellation never counts as verified success ----------------------


async def test_cancellation_shaped_failure_never_counts_as_verified_success(
    db_session: Session,
) -> None:
    registry = ExecutorRegistry()
    registry.register("demo", FailingExecutor(error_type="CANCELLED"))
    service = _service(db_session, registry=registry, candidates=[build_candidate("demo")])
    result = await service.orchestrate(_request())

    assert result.outcome != OrchestrationOutcome.VERIFIED_SUCCESS


# --- 19. Manager called exactly once -----------------------------------------


async def test_manager_called_exactly_once_per_orchestration(db_session: Session) -> None:
    registry, _ = _registry_with_demo()
    fake_model = FakeManagerModel(exception=ManagerUnavailableError("down"))
    service = _service(
        db_session,
        registry=registry,
        candidates=[build_candidate("demo")],
        manager_model=fake_model,
    )
    await service.orchestrate(_request())
    assert len(fake_model.calls) == 1


# --- 20/27. Learning written once, deterministic IDs -------------------------


async def test_learning_event_ids_unique_and_match_deterministic_scheme(
    db_session: Session,
) -> None:
    registry, _ = _registry_with_demo()
    service = _service(db_session, registry=registry, candidates=[build_candidate("demo")])
    result = await service.orchestrate(_request())

    assert len(set(result.learning_event_ids)) == len(result.learning_event_ids)
    for event_id in result.learning_event_ids:
        assert event_id.startswith(f"evt-{result.workflow_id}-")


# --- 21. No CoT / raw manager content leak -----------------------------------


async def test_result_never_exposes_reasoning_or_raw_manager_content(db_session: Session) -> None:
    registry, _ = _registry_with_demo()
    request = _request(available_agent_types=["demo"])
    manager_response = ManagerResponse(
        request_id=request.request_id, provider_identifier="fake-manager"
    )
    fake_model = FakeManagerModel(response=manager_response)
    service = _service(
        db_session,
        registry=registry,
        candidates=[build_candidate("demo")],
        manager_model=fake_model,
    )
    result = await service.orchestrate(request)
    dump = repr(result)
    for forbidden in ("reasoning_content", "chain_of_thought", "<think>", "scratchpad"):
        assert forbidden not in dump


# --- 22. No secret leak ------------------------------------------------------


async def test_result_never_exposes_credential_shaped_content(db_session: Session) -> None:
    registry, _ = _registry_with_demo()
    service = _service(db_session, registry=registry, candidates=[build_candidate("demo")])
    result = await service.orchestrate(_request())
    dump = repr(result)
    for forbidden in ("Authorization", "Bearer ", "api_key", "NVIDIA_API_KEY"):
        assert forbidden not in dump


# --- 23. Determinism ----------------------------------------------------------


async def test_deterministic_fake_dependencies_produce_deterministic_summary(
    db_session: Session,
) -> None:
    results = []
    for _ in range(3):
        registry, _ = _registry_with_demo()
        service = _service(db_session, registry=registry, candidates=[build_candidate("demo")])
        request = _request(request_id="req-fixed")
        results.append(await service.orchestrate(request))

    first = results[0]
    for result in results[1:]:
        assert result.outcome == first.outcome
        assert result.task_count == first.task_count
        assert result.step_count == first.step_count
        assert result.selected_agent_types == first.selected_agent_types
        assert result.verification_status == first.verification_status


# --- 24. Existing Stage 8A fallback wording unchanged ------------------------


async def test_existing_manager_fallback_warning_wording_unchanged(db_session: Session) -> None:
    registry, _ = _registry_with_demo()
    fake_model = FakeManagerModel(exception=ManagerUnavailableError("down"))
    service = _service(
        db_session,
        registry=registry,
        candidates=[build_candidate("demo")],
        manager_model=fake_model,
    )
    result = await service.orchestrate(_request())
    assert any("using deterministic fallback" in w for w in result.warnings)


# --- Sanity: build_event_id reused unmodified --------------------------------


def test_build_event_id_matches_expected_format() -> None:
    assert build_event_id("wf-1", "step-1", 1) == "evt-wf-1-step-1-1"
