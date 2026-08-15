"""Stage 9E: `EngineeringIntelligenceQueryService` -- deterministic queries
over the Engineering Intelligence Graph.

Every method here is a pure aggregation over already-persisted graph rows:
no LLM calls, no speculative inference, no hidden state. A derived rate is
always returned alongside the raw counts it comes from (see
`app.contracts.intelligence`'s `sample_size_is_low` properties) so a caller
can judge for itself whether a rate is backed by enough evidence to act on.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from app.contracts.intelligence import (
    AgentReliabilityObservation,
    FailureAttribution,
    FailureAttributionCategory,
    IntelligenceEdge,
    IntelligenceNode,
    IntelligenceNodeType,
    QualityGateIntelligence,
    SkillReliabilityObservation,
    TaskReliabilityObservation,
)
from app.engine.intelligence.graph_repository import IntelligenceGraphRepository


def _is_recovering_attempt(node: IntelligenceNode) -> bool:
    attempt_number = node.metadata.get("attempt_number")
    return isinstance(attempt_number, int) and attempt_number > 1


class EngineeringIntelligenceQueryService:
    """Read-only query layer over one `IntelligenceGraphRepository`."""

    def __init__(self, graph_repo: IntelligenceGraphRepository) -> None:
        self._graph_repo = graph_repo

    # --- Node / provenance lookup -------------------------------------------

    def get_node(self, node_id: str) -> IntelligenceNode | None:
        return self._graph_repo.get_node(node_id)

    def get_relationships(
        self, node_id: str
    ) -> tuple[list[IntelligenceEdge], list[IntelligenceEdge]]:
        """Return `(outgoing, incoming)` edges for `node_id` -- the
        provenance trail a caller can follow to retrieve the underlying
        evidence behind any reliability/failure observation."""
        return self._graph_repo.get_edges_from(node_id), self._graph_repo.get_edges_to(node_id)

    # --- Reliability signals -------------------------------------------------

    def get_task_reliability(
        self, *, task_type: str | None = None, since: datetime | None = None
    ) -> TaskReliabilityObservation:
        attempts = self._graph_repo.get_nodes_by_type(
            IntelligenceNodeType.ATTEMPT, task_type=task_type, since=since
        )
        success_count = sum(1 for a in attempts if a.status == "succeeded")
        failure_count = sum(1 for a in attempts if a.status == "failed")
        recovery_count = sum(1 for a in attempts if _is_recovering_attempt(a))
        rejection_count = len(
            self._graph_repo.list_failure_attributions(
                task_type=task_type,
                category=FailureAttributionCategory.QUALITY_GATE_FAILURE,
                since=since,
                limit=len(attempts) + 1 if attempts else 100,
            )
        ) + len(
            self._graph_repo.list_failure_attributions(
                task_type=task_type,
                category=FailureAttributionCategory.SKILL_VERIFICATION_FAILURE,
                since=since,
                limit=len(attempts) + 1 if attempts else 100,
            )
        )
        return TaskReliabilityObservation(
            task_type=task_type,
            attempt_count=len(attempts),
            success_count=success_count,
            failure_count=failure_count,
            recovery_count=recovery_count,
            quality_rejection_count=rejection_count,
        )

    def get_agent_reliability(
        self,
        agent_type: str,
        *,
        task_type: str | None = None,
        since: datetime | None = None,
    ) -> AgentReliabilityObservation:
        attempts = self._graph_repo.get_nodes_by_type(
            IntelligenceNodeType.ATTEMPT,
            agent_type=agent_type,
            task_type=task_type,
            since=since,
        )
        successful = [a for a in attempts if a.status == "succeeded"]
        failed = [a for a in attempts if a.status == "failed"]
        recovery_count = sum(1 for a in attempts if _is_recovering_attempt(a))
        quality_runs = self._graph_repo.get_nodes_by_type(
            IntelligenceNodeType.QUALITY_RUN,
            agent_type=agent_type,
            task_type=task_type,
            since=since,
        )
        quality_verified_successes = sum(
            1 for r in quality_runs if r.metadata.get("passed") is True
        )
        return AgentReliabilityObservation(
            agent_type=agent_type,
            task_type=task_type,
            observed_executions=len(attempts),
            successful_executions=len(successful),
            failed_executions=len(failed),
            recovery_count=recovery_count,
            quality_verified_successes=quality_verified_successes,
        )

    def get_skill_reliability(
        self,
        skill_id: str,
        skill_version: str | None = None,
        *,
        task_type: str | None = None,
        since: datetime | None = None,
    ) -> SkillReliabilityObservation:
        attempts = self._graph_repo.get_nodes_by_type(
            IntelligenceNodeType.ATTEMPT,
            skill_id=skill_id,
            skill_version=skill_version,
            task_type=task_type,
            since=since,
        )
        successful = [a for a in attempts if a.status == "succeeded"]
        failed = [a for a in attempts if a.status == "failed"]
        quality_runs = self._graph_repo.get_nodes_by_type(
            IntelligenceNodeType.QUALITY_RUN,
            skill_id=skill_id,
            skill_version=skill_version,
            task_type=task_type,
            since=since,
        )
        quality_verified_uses = sum(1 for r in quality_runs if r.metadata.get("passed") is True)
        return SkillReliabilityObservation(
            skill_id=skill_id,
            skill_version=skill_version,
            task_type=task_type,
            uses=len(attempts),
            successful_uses=len(successful),
            failed_uses=len(failed),
            quality_verified_uses=quality_verified_uses,
        )

    def get_quality_gate_intelligence(
        self,
        *,
        task_type: str | None = None,
        agent_type: str | None = None,
        skill_id: str | None = None,
        since: datetime | None = None,
    ) -> QualityGateIntelligence:
        gates = self._graph_repo.get_nodes_by_type(
            IntelligenceNodeType.QUALITY_GATE,
            task_type=task_type,
            agent_type=agent_type,
            skill_id=skill_id,
            since=since,
        )
        status_counts = Counter(g.status for g in gates)
        failed_gate_types = Counter(
            g.metadata.get("gate_type", "unknown")
            for g in gates
            if g.status in ("FAILED", "ERROR")
        )
        return QualityGateIntelligence(
            task_type=task_type,
            agent_type=agent_type,
            skill_id=skill_id,
            total_gate_results=len(gates),
            passed_count=status_counts.get("PASSED", 0),
            failed_count=status_counts.get("FAILED", 0),
            error_count=status_counts.get("ERROR", 0),
            skipped_count=status_counts.get("SKIPPED", 0),
            most_frequent_failed_gate_types=tuple(failed_gate_types.most_common()),
        )

    # --- Failure attribution --------------------------------------------------

    def get_failure_history(
        self,
        *,
        task_type: str | None = None,
        agent_type: str | None = None,
        skill_id: str | None = None,
        category: FailureAttributionCategory | None = None,
        since: datetime | None = None,
        limit: int = 50,
    ) -> list[FailureAttribution]:
        return self._graph_repo.list_failure_attributions(
            task_type=task_type,
            agent_type=agent_type,
            skill_id=skill_id,
            category=category,
            since=since,
            limit=limit,
        )

    # --- Recent observations ---------------------------------------------------

    def get_recent_observations(
        self, *, since: datetime, limit: int = 50
    ) -> dict[str, list[IntelligenceNode] | list[FailureAttribution]]:
        """A deterministic snapshot of what happened since `since` -- recent
        attempts, quality runs, and failure attributions -- for a caller
        (e.g. a future recommendation layer) to consume without doing its
        own graph traversal. Never invokes an LLM; purely a bounded read."""
        return {
            "attempts": self._graph_repo.get_nodes_by_type(
                IntelligenceNodeType.ATTEMPT, since=since
            )[:limit],
            "quality_runs": self._graph_repo.get_nodes_by_type(
                IntelligenceNodeType.QUALITY_RUN, since=since
            )[:limit],
            "failures": self._graph_repo.list_failure_attributions(since=since, limit=limit),
        }


__all__ = ["EngineeringIntelligenceQueryService"]
