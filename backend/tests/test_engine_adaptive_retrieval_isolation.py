"""Stage 7.5 ISOLATION tests: adaptive retrieval learning never mutates
`Router`, `AgentPassport`/`PassportEvidenceProvider`, or Stage 5 learning
history -- Stage 8's future manager, not Stage 7.5, will ever wire these
systems together."""

from datetime import UTC, datetime

from app.contracts.enums import AgentExecutionStatus
from app.contracts.verification import VerificationStatus
from app.engine.adaptive_retrieval.feedback import RetrievalFeedback
from app.engine.adaptive_retrieval.passport import rebuild_all_retrieval_passports
from app.engine.adaptive_retrieval.policy import AdaptiveRetrievalPolicy
from app.engine.adaptive_retrieval.reranking import AdaptiveRetriever
from app.engine.knowledge.chunking import chunk_document
from app.engine.knowledge.index import KnowledgeIndex
from app.engine.knowledge.models import KnowledgeDocument
from app.engine.knowledge.retrieval import KnowledgeSearchRequest
from app.engine.learning.events import LearningEvent
from app.engine.learning.evidence import PassportEvidenceProvider, build_passport_evidence_provider
from app.engine.routing.evidence import NullEvidenceProvider
from app.engine.routing.router import Router

_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _index() -> KnowledgeIndex:
    doc = KnowledgeDocument(
        document_id="doc-1", source_id="src-1", title="Doc", content="reliability alpha content"
    )
    index = KnowledgeIndex()
    index.upsert_document(doc, chunk_document(doc))
    return index


def _production_event(agent_type: str = "shared-agent") -> LearningEvent:
    return LearningEvent(
        event_id="prod-1",
        workflow_id="wf-1",
        agent_type=agent_type,
        execution_status=AgentExecutionStatus.SUCCEEDED,
        created_at=_CREATED_AT,
        task_type="fix",
        verification_status=VerificationStatus.PASSED,
    )


def test_adaptive_retrieval_does_not_touch_router() -> None:
    index = _index()
    request = KnowledgeSearchRequest(query="reliability")
    chunk = index.all_chunks()[0]

    router = Router(evidence=NullEvidenceProvider())

    feedback = [
        RetrievalFeedback(
            retrieval_id=f"retrieval::sample-{i}",
            chunk_ids=(chunk.chunk_id,),
            verification_status=VerificationStatus.PASSED,
            task_type="fix",
            repository_id="org/repo",
            execution_status=AgentExecutionStatus.SUCCEEDED,
        )
        for i in range(6)
    ]
    passports = rebuild_all_retrieval_passports(feedback)
    retriever = AdaptiveRetriever(policy=AdaptiveRetrievalPolicy(enabled=True))
    retriever.retrieve(
        index, request, task_type="fix", repository_id="org/repo", production_passports=passports
    )

    assert router._evidence.overall_metrics("shared-agent") is None  # untouched


def test_adaptive_retrieval_does_not_touch_production_passport_evidence_provider() -> None:
    production_provider = build_passport_evidence_provider(
        [_production_event()], updated_at=_CREATED_AT
    )
    before = production_provider.overall_metrics("shared-agent")
    assert before is not None

    index = _index()
    request = KnowledgeSearchRequest(query="reliability")
    chunk = index.all_chunks()[0]
    feedback = [
        RetrievalFeedback(
            retrieval_id=f"retrieval::sample-{i}",
            chunk_ids=(chunk.chunk_id,),
            verification_status=VerificationStatus.PASSED,
            task_type="fix",
            execution_status=AgentExecutionStatus.SUCCEEDED,
        )
        for i in range(6)
    ]
    passports = rebuild_all_retrieval_passports(feedback)
    AdaptiveRetriever(policy=AdaptiveRetrievalPolicy(enabled=True)).retrieve(
        index, request, task_type="fix", production_passports=passports
    )

    after = production_provider.overall_metrics("shared-agent")
    assert after == before


def test_adaptive_retrieval_never_constructs_a_passport_evidence_provider_itself() -> None:
    """Structural check: nothing in the adaptive_retrieval package imports
    Router or the production evidence-provider machinery -- retrieval
    learning and Router evidence stay entirely separate call graphs."""
    import app.engine.adaptive_retrieval.feedback as feedback_module
    import app.engine.adaptive_retrieval.models as models_module
    import app.engine.adaptive_retrieval.passport as passport_module
    import app.engine.adaptive_retrieval.policy as policy_module
    import app.engine.adaptive_retrieval.reranking as reranking_module
    import app.engine.adaptive_retrieval.scoring as scoring_module

    for module in (
        feedback_module, models_module, passport_module, policy_module,
        reranking_module, scoring_module,
    ):
        source_file = module.__file__
        assert source_file is not None
        with open(source_file, encoding="utf-8") as fh:
            source = fh.read()
        assert "app.engine.routing" not in source
        assert "PassportEvidenceProvider" not in source


def test_empty_production_provider_untouched_by_unrelated_retrieval_learning() -> None:
    production_provider = PassportEvidenceProvider(passports={})
    assert production_provider.overall_metrics("any-agent") is None

    index = _index()
    request = KnowledgeSearchRequest(query="reliability")
    AdaptiveRetriever(policy=AdaptiveRetrievalPolicy(enabled=False)).retrieve(index, request)

    assert production_provider.overall_metrics("any-agent") is None
