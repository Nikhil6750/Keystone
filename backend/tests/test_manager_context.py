"""Tests for `app.engine.manager.context.build_manager_request`: bounded,
deterministic assembly from Keystone's existing knowledge/routing output."""

from app.contracts.enums import AgentCapability
from app.contracts.knowledge import KnowledgeSearchResult
from app.engine.manager.context import build_manager_request
from app.engine.manager.models import MAX_AVAILABLE_AGENT_TYPES, MAX_KNOWLEDGE_CONTEXT_ITEMS


def _knowledge(document_id: str, score: float) -> KnowledgeSearchResult:
    return KnowledgeSearchResult(
        document_id=document_id, vault_id="vault", title="t", snippet="s", score=score
    )


def test_builds_minimal_request() -> None:
    request = build_manager_request(request_id="req-1", goal="Implement feature X")
    assert request.request_id == "req-1"
    assert request.goal == "Implement feature X"
    assert request.knowledge_context == []


def test_truncates_oversized_knowledge_context_deterministically() -> None:
    items = [_knowledge(f"doc-{i}", score=float(i)) for i in range(30)]
    request = build_manager_request(
        request_id="req-1", goal="goal", knowledge_context=items
    )
    assert len(request.knowledge_context) == MAX_KNOWLEDGE_CONTEXT_ITEMS
    # Highest score first (doc-29 has score 29.0, the maximum).
    assert request.knowledge_context[0].document_id == "doc-29"
    scores = [item.score for item in request.knowledge_context]
    assert scores == sorted(scores, reverse=True)


def test_knowledge_context_truncation_is_deterministic_across_calls() -> None:
    items = [_knowledge(f"doc-{i}", score=float(i % 5)) for i in range(30)]
    first = build_manager_request(request_id="req-1", goal="goal", knowledge_context=items)
    second = build_manager_request(request_id="req-1", goal="goal", knowledge_context=items)
    assert [item.document_id for item in first.knowledge_context] == [
        item.document_id for item in second.knowledge_context
    ]


def test_truncates_oversized_agent_type_list_deterministically() -> None:
    agent_types = [f"agent-{i}" for i in range(80)]
    request = build_manager_request(
        request_id="req-1", goal="goal", available_agent_types=agent_types
    )
    assert len(request.available_agent_types) == MAX_AVAILABLE_AGENT_TYPES
    assert request.available_agent_types == sorted(request.available_agent_types)


def test_dedupes_agent_types() -> None:
    request = build_manager_request(
        request_id="req-1",
        goal="goal",
        available_agent_types=["claude_code", "claude_code", "codex"],
    )
    assert request.available_agent_types == ["claude_code", "codex"]


def test_dedupes_and_sorts_capabilities() -> None:
    request = build_manager_request(
        request_id="req-1",
        goal="goal",
        available_capabilities=[
            AgentCapability.TEST_GENERATION,
            AgentCapability.CODE_GENERATION,
            AgentCapability.CODE_GENERATION,
        ],
    )
    assert request.available_capabilities == [
        AgentCapability.CODE_GENERATION,
        AgentCapability.TEST_GENERATION,
    ]


def test_never_touches_a_filesystem() -> None:
    """Sanity check for the knowledge-integration boundary (Stage 8A rule
    11): `build_manager_request` accepts only already-retrieved
    `KnowledgeSearchResult`s and has no path/file parameter at all."""
    import inspect

    signature = inspect.signature(build_manager_request)
    for name in signature.parameters:
        assert "path" not in name.lower()
        assert "file" not in name.lower()
