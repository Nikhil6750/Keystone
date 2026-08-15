"""`build_manager_request`: the one place a `ManagerRequest` is assembled
from Keystone's existing components' output.

**Knowledge integration boundary (Stage 8A rule 11).** This function accepts
already-retrieved `KnowledgeSearchResult`s -- the existing Knowledge Engine /
Adaptive Retrieval pipeline's own output -- and never touches a filesystem,
vault, or Markdown source itself. There is no code path in this module (or
anywhere in `app.engine.manager`) that opens a file.

**Deterministic bounding, never rejection, for abundance.** If the caller
hands this function more knowledge results, agent types, or capabilities
than `ManagerRequest` allows, they are deterministically downselected here
(highest `KnowledgeSearchResult.score` first, ties broken by `document_id`;
agent types/capabilities sorted lexicographically) rather than raising --
mirroring `app.engine.knowledge.context.ContextBuilder`'s own "budget, don't
fail" philosophy for a caller that legitimately has more candidates
available than the bounded request can carry. This is downselection of
abundant, well-formed input, not repair of a malformed one -- the "never
silently invent a replacement" rule (Stage 8A rule 7) governs unknown/unsafe
*values*, not the ordinary act of keeping the top-N of an oversupplied,
already-valid list.
"""

from collections.abc import Iterable

from app.contracts.enums import AgentCapability
from app.contracts.knowledge import KnowledgeSearchResult
from app.contracts.routing import RoutingConstraints
from app.engine.manager.models import (
    MAX_AVAILABLE_AGENT_TYPES,
    MAX_AVAILABLE_CAPABILITIES,
    MAX_KNOWLEDGE_CONTEXT_ITEMS,
    ManagerRecoveryContext,
    ManagerRequest,
)


def _bounded_knowledge_context(
    results: Iterable[KnowledgeSearchResult],
) -> list[KnowledgeSearchResult]:
    ordered = sorted(results, key=lambda result: (-result.score, result.document_id))
    return ordered[:MAX_KNOWLEDGE_CONTEXT_ITEMS]


def _bounded_agent_types(agent_types: Iterable[str]) -> list[str]:
    return sorted(set(agent_types))[:MAX_AVAILABLE_AGENT_TYPES]


def _bounded_capabilities(
    capabilities: Iterable[AgentCapability],
) -> list[AgentCapability]:
    ordered = sorted({capability for capability in capabilities}, key=lambda item: item.value)
    return ordered[:MAX_AVAILABLE_CAPABILITIES]


def build_manager_request(
    *,
    request_id: str,
    goal: str,
    task_type: str | None = None,
    repository_id: str | None = None,
    available_agent_types: Iterable[str] = (),
    available_capabilities: Iterable[AgentCapability] = (),
    knowledge_context: Iterable[KnowledgeSearchResult] = (),
    workflow_constraints: RoutingConstraints | None = None,
    recovery_context: ManagerRecoveryContext | None = None,
) -> ManagerRequest:
    """Assemble a bounded `ManagerRequest` from Keystone's existing
    components' output. Every bound is `ManagerRequest`'s own -- this
    function only decides *which* items survive when there are too many,
    never relaxes a bound."""
    return ManagerRequest(
        request_id=request_id,
        goal=goal,
        task_type=task_type,
        repository_id=repository_id,
        available_agent_types=_bounded_agent_types(available_agent_types),
        available_capabilities=_bounded_capabilities(available_capabilities),
        knowledge_context=_bounded_knowledge_context(knowledge_context),
        workflow_constraints=workflow_constraints,
        recovery_context=recovery_context,
    )


__all__ = ["build_manager_request"]
