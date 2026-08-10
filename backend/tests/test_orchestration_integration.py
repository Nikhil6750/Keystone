"""Stage 8C.1 Part 11: one high-value offline integration test proving the
actual composition of real Keystone components, not a mock-every-method
unit test.

Real: `KnowledgeIndex`, `AdaptiveRetriever`, `ManagerOrchestrator`,
`Planner`, `Router`, the real `WorkflowEngine` (SQLite-backed, isolated per
test via `db_session`), the real Stage 4E verifier (`verify_one`/
`aggregate`, invoked through `WorkflowEngine`'s own `VerificationResolver`
seam), the real `LearningPersistenceService`, and a real
`InMemoryRetrievalFeedbackRepository`.

Fake (external boundaries only, per Part 5): `FakeManagerModel` (no live
NVIDIA call) and `RecordingExecutor` (no live agent CLI). Both are
existing test doubles already certified by Stage 8A/8B and the engine test
suite -- nothing new is faked here beyond what those stages already do.
"""

import uuid

from sqlalchemy.orm import Session

from app.contracts.enums import AgentCapability
from app.engine.adaptive_retrieval.feedback import InMemoryRetrievalFeedbackRepository
from app.engine.adaptive_retrieval.policy import AdaptiveRetrievalPolicy
from app.engine.adaptive_retrieval.reranking import AdaptiveRetriever
from app.engine.knowledge.index import KnowledgeIndex
from app.engine.knowledge.models import KnowledgeChunk, KnowledgeDocument
from app.engine.manager.fake import FakeManagerModel
from app.engine.manager.models import ManagerResponse, ManagerTaskProposal
from app.engine.orchestration.models import OrchestrationOutcome, OrchestrationRequest
from app.engine.orchestration.runtime import StaticCandidateProvider
from app.engine.orchestration.service import EndToEndOrchestrationService
from app.engine.registry import ExecutorRegistry
from app.models.enums import WorkflowStatus
from app.persistence.service import LearningPersistenceService
from app.resilience.circuit_breaker import CircuitBreakerRegistry
from app.resilience.retry import RetryPolicy
from tests.support.executors import RecordingExecutor
from tests.support.orchestration_fakes import RICH_SUCCESS_OUTPUT, build_candidate


async def test_full_real_pipeline_composition(db_session: Session) -> None:
    # --- Real Knowledge Engine + real Stage 7.5 adaptive retrieval --------
    index = KnowledgeIndex()
    content = "Implement user authentication with tests using JWT tokens and refresh flow"
    document = KnowledgeDocument(
        document_id="doc-auth",
        source_id="vault",
        title="Authentication design notes",
        content=content,
    )
    chunk = KnowledgeChunk(
        chunk_id="chunk-auth", document_id="doc-auth", source_id="vault", content=content, ordinal=0
    )
    index.upsert_document(document, [chunk])
    adaptive_retriever = AdaptiveRetriever(policy=AdaptiveRetrievalPolicy(enabled=True))

    # --- Real Router candidates (no live registry/connection cache needed) --
    registry = ExecutorRegistry()
    executor = RecordingExecutor(output=dict(RICH_SUCCESS_OUTPUT))
    registry.register("claude_code", executor)
    candidate_provider = StaticCandidateProvider(agents=(build_candidate("claude_code"),))

    # --- Fake Manager only (external boundary) -----------------------------
    request = OrchestrationRequest(
        request_id=f"req-{uuid.uuid4().hex[:8]}",
        goal="Implement user authentication with tests",
        available_agent_types=["claude_code"],
        available_capabilities=[AgentCapability.CODE_GENERATION],
    )
    manager_response = ManagerResponse(
        request_id=request.request_id,
        provider_identifier="fake-manager-integration",
        task_proposals=[
            ManagerTaskProposal(
                key="t1", description="do it", preferred_agent_types=["claude_code"]
            )
        ],
    )
    manager_model = FakeManagerModel(response=manager_response)

    # --- Real learning persistence + real retrieval feedback repository ---
    learning_persistence = LearningPersistenceService()
    retrieval_feedback_repository = InMemoryRetrievalFeedbackRepository()

    service = EndToEndOrchestrationService(
        db=db_session,
        registry=registry,
        candidate_provider=candidate_provider,
        manager_model=manager_model,
        knowledge_index=index,
        adaptive_retriever=adaptive_retriever,
        retrieval_feedback_repository=retrieval_feedback_repository,
        learning_persistence=learning_persistence,
        circuit_breakers=CircuitBreakerRegistry(failure_threshold=3, recovery_timeout_seconds=30.0),
        retry_policy=RetryPolicy(base_delay_seconds=0.01, max_delay_seconds=0.05),
    )

    result = await service.orchestrate(request)

    # --- Prove the actual composition, not just isolated pieces -----------
    assert result.outcome == OrchestrationOutcome.VERIFIED_SUCCESS
    assert result.manager_used is True
    assert result.manager_fallback_used is False
    assert result.manager_proposal_validated is True
    assert result.manager_provider_identifier == "fake-manager-integration"
    assert result.knowledge_result_count == 1
    assert result.adaptive_retrieval_used is True
    assert result.selected_agent_types == ("claude_code",)
    assert result.final_workflow_state == WorkflowStatus.SUCCEEDED
    assert result.verification_status is not None and result.verification_status.value == "passed"
    assert result.retrieval_feedback_recorded is True
    assert len(manager_model.calls) == 1
    assert len(executor.calls) == result.task_count

    # Learning events genuinely persisted (real repository, not a fake).
    # Not every task necessarily carries an ExpectedOutcome (a task with
    # none is simply not a required verification check -- see
    # `app.engine.verification.aggregation`), so only assert every stored
    # event exists and, where a verification_status was recorded, it is
    # never silently wrong (PASSED given the rich success output).
    stored_events = [
        learning_persistence.get_learning_event(db_session, event_id)
        for event_id in result.learning_event_ids
    ]
    assert all(event is not None for event in stored_events)
    verified_statuses = [
        event.verification_status.value
        for event in stored_events
        if event is not None and event.verification_status is not None
    ]
    assert verified_statuses  # at least one step actually had an ExpectedOutcome checked
    assert all(status == "passed" for status in verified_statuses)

    # Retrieval feedback is real, verified, and positive.
    feedback_records = retrieval_feedback_repository.all()
    assert len(feedback_records) == 1
    assert feedback_records[0].is_verified_success is True
    assert feedback_records[0].execution_id == result.workflow_id
