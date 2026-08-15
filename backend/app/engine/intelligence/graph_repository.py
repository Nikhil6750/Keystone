"""Persistence layer for the Stage 9E Engineering Intelligence Graph.

Mirrors `app.engine.quality.repository`'s shape deliberately: a `Protocol`,
an `InMemory...` implementation for tests, and a `SqlAlchemy...`
implementation for production, all sharing the same interface.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.intelligence import (
    FailureAttribution,
    FailureAttributionCategory,
    IntelligenceEdge,
    IntelligenceEdgeType,
    IntelligenceNode,
    IntelligenceNodeType,
)
from app.models.intelligence import (
    FailureAttributionRecord,
    IntelligenceEdgeRecord,
    IntelligenceNodeRecord,
)


def _node_from_record(rec: IntelligenceNodeRecord) -> IntelligenceNode:
    return IntelligenceNode(
        node_id=rec.node_id,
        node_type=IntelligenceNodeType(rec.node_type),
        canonical_id=rec.canonical_id,
        label=rec.label,
        workflow_id=rec.workflow_id,
        agent_type=rec.agent_type,
        task_type=rec.task_type,
        skill_id=rec.skill_id,
        skill_version=rec.skill_version,
        status=rec.status,
        metadata=dict(rec.metadata_json),
        created_at=rec.created_at,
    )


def _record_from_node(node: IntelligenceNode) -> IntelligenceNodeRecord:
    return IntelligenceNodeRecord(
        node_id=node.node_id,
        node_type=node.node_type.value,
        canonical_id=node.canonical_id,
        label=node.label,
        workflow_id=node.workflow_id,
        agent_type=node.agent_type,
        task_type=node.task_type,
        skill_id=node.skill_id,
        skill_version=node.skill_version,
        status=node.status,
        metadata_json=dict(node.metadata),
        created_at=node.created_at,
    )


def _edge_from_record(rec: IntelligenceEdgeRecord) -> IntelligenceEdge:
    return IntelligenceEdge(
        edge_id=rec.edge_id,
        edge_type=IntelligenceEdgeType(rec.edge_type),
        source_node_id=rec.source_node_id,
        target_node_id=rec.target_node_id,
        metadata=dict(rec.metadata_json),
        created_at=rec.created_at,
    )


def _record_from_edge(edge: IntelligenceEdge) -> IntelligenceEdgeRecord:
    return IntelligenceEdgeRecord(
        edge_id=edge.edge_id,
        edge_type=edge.edge_type.value,
        source_node_id=edge.source_node_id,
        target_node_id=edge.target_node_id,
        metadata_json=dict(edge.metadata),
        created_at=edge.created_at,
    )


def _attribution_from_record(rec: FailureAttributionRecord) -> FailureAttribution:
    return FailureAttribution(
        attribution_id=rec.attribution_id,
        attempt_node_id=rec.attempt_node_id,
        category=FailureAttributionCategory(rec.category),
        is_known=rec.is_known,
        explanation=rec.explanation,
        evidence_ids=tuple(rec.evidence_ids),
        workflow_id=rec.workflow_id,
        agent_type=rec.agent_type,
        task_type=rec.task_type,
        skill_id=rec.skill_id,
        created_at=rec.created_at,
    )


def _record_from_attribution(attribution: FailureAttribution) -> FailureAttributionRecord:
    return FailureAttributionRecord(
        attribution_id=attribution.attribution_id,
        attempt_node_id=attribution.attempt_node_id,
        category=attribution.category.value,
        is_known=attribution.is_known,
        explanation=attribution.explanation,
        evidence_ids=list(attribution.evidence_ids),
        workflow_id=attribution.workflow_id,
        agent_type=attribution.agent_type,
        task_type=attribution.task_type,
        skill_id=attribution.skill_id,
        created_at=attribution.created_at,
    )


class IntelligenceGraphRepository(Protocol):
    """Persistence operations for the Engineering Intelligence Graph.

    `upsert_node`/`upsert_edge`/`upsert_failure_attribution` are
    insert-if-absent by deterministic id -- never update-in-place -- so
    replaying the same source evidence is always idempotent and a later
    ingestion pass can never overwrite earlier historical evidence.
    Returns `True` iff a new row was actually inserted.
    """

    def upsert_node(self, node: IntelligenceNode) -> bool: ...

    def upsert_edge(self, edge: IntelligenceEdge) -> bool: ...

    def upsert_failure_attribution(self, attribution: FailureAttribution) -> bool: ...

    def get_node(self, node_id: str) -> IntelligenceNode | None: ...

    def get_nodes_by_type(
        self,
        node_type: IntelligenceNodeType,
        *,
        workflow_id: str | None = None,
        agent_type: str | None = None,
        task_type: str | None = None,
        skill_id: str | None = None,
        skill_version: str | None = None,
        since: object = None,
    ) -> list[IntelligenceNode]: ...

    def get_edges_from(self, node_id: str) -> list[IntelligenceEdge]: ...

    def get_edges_to(self, node_id: str) -> list[IntelligenceEdge]: ...

    def list_failure_attributions(
        self,
        *,
        workflow_id: str | None = None,
        agent_type: str | None = None,
        task_type: str | None = None,
        skill_id: str | None = None,
        category: FailureAttributionCategory | None = None,
        since: object = None,
        limit: int = 100,
    ) -> list[FailureAttribution]: ...


class InMemoryIntelligenceGraphRepository:
    """Deterministic in-memory graph repository for unit testing."""

    def __init__(self) -> None:
        self._nodes: dict[str, IntelligenceNode] = {}
        self._edges: dict[str, IntelligenceEdge] = {}
        self._attributions: dict[str, FailureAttribution] = {}

    def upsert_node(self, node: IntelligenceNode) -> bool:
        if node.node_id in self._nodes:
            return False
        self._nodes[node.node_id] = node
        return True

    def upsert_edge(self, edge: IntelligenceEdge) -> bool:
        if edge.edge_id in self._edges:
            return False
        self._edges[edge.edge_id] = edge
        return True

    def upsert_failure_attribution(self, attribution: FailureAttribution) -> bool:
        if attribution.attribution_id in self._attributions:
            return False
        self._attributions[attribution.attribution_id] = attribution
        return True

    def get_node(self, node_id: str) -> IntelligenceNode | None:
        return self._nodes.get(node_id)

    def get_nodes_by_type(
        self,
        node_type: IntelligenceNodeType,
        *,
        workflow_id: str | None = None,
        agent_type: str | None = None,
        task_type: str | None = None,
        skill_id: str | None = None,
        skill_version: str | None = None,
        since: object = None,
    ) -> list[IntelligenceNode]:
        results = [n for n in self._nodes.values() if n.node_type is node_type]
        if workflow_id is not None:
            results = [n for n in results if n.workflow_id == workflow_id]
        if agent_type is not None:
            results = [n for n in results if n.agent_type == agent_type]
        if task_type is not None:
            results = [n for n in results if n.task_type == task_type]
        if skill_id is not None:
            results = [n for n in results if n.skill_id == skill_id]
        if skill_version is not None:
            results = [n for n in results if n.skill_version == skill_version]
        if since is not None:
            results = [n for n in results if n.created_at >= since]  # type: ignore[operator]
        return sorted(results, key=lambda n: n.node_id)

    def get_edges_from(self, node_id: str) -> list[IntelligenceEdge]:
        return sorted(
            (e for e in self._edges.values() if e.source_node_id == node_id),
            key=lambda e: e.edge_id,
        )

    def get_edges_to(self, node_id: str) -> list[IntelligenceEdge]:
        return sorted(
            (e for e in self._edges.values() if e.target_node_id == node_id),
            key=lambda e: e.edge_id,
        )

    def list_failure_attributions(
        self,
        *,
        workflow_id: str | None = None,
        agent_type: str | None = None,
        task_type: str | None = None,
        skill_id: str | None = None,
        category: FailureAttributionCategory | None = None,
        since: object = None,
        limit: int = 100,
    ) -> list[FailureAttribution]:
        results = list(self._attributions.values())
        if workflow_id is not None:
            results = [a for a in results if a.workflow_id == workflow_id]
        if agent_type is not None:
            results = [a for a in results if a.agent_type == agent_type]
        if task_type is not None:
            results = [a for a in results if a.task_type == task_type]
        if skill_id is not None:
            results = [a for a in results if a.skill_id == skill_id]
        if category is not None:
            results = [a for a in results if a.category is category]
        if since is not None:
            results = [a for a in results if a.created_at >= since]  # type: ignore[operator]
        results.sort(key=lambda a: a.created_at, reverse=True)
        return results[:limit]


class SqlAlchemyIntelligenceGraphRepository:
    """Production SQLAlchemy persistence for the Engineering Intelligence Graph."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def upsert_node(self, node: IntelligenceNode) -> bool:
        with self._session_factory() as session:
            if session.get(IntelligenceNodeRecord, node.node_id) is not None:
                return False
            session.add(_record_from_node(node))
            session.commit()
            return True

    def upsert_edge(self, edge: IntelligenceEdge) -> bool:
        with self._session_factory() as session:
            if session.get(IntelligenceEdgeRecord, edge.edge_id) is not None:
                return False
            session.add(_record_from_edge(edge))
            session.commit()
            return True

    def upsert_failure_attribution(self, attribution: FailureAttribution) -> bool:
        with self._session_factory() as session:
            if session.get(FailureAttributionRecord, attribution.attribution_id) is not None:
                return False
            session.add(_record_from_attribution(attribution))
            session.commit()
            return True

    def get_node(self, node_id: str) -> IntelligenceNode | None:
        with self._session_factory() as session:
            rec = session.get(IntelligenceNodeRecord, node_id)
            return _node_from_record(rec) if rec else None

    def get_nodes_by_type(
        self,
        node_type: IntelligenceNodeType,
        *,
        workflow_id: str | None = None,
        agent_type: str | None = None,
        task_type: str | None = None,
        skill_id: str | None = None,
        skill_version: str | None = None,
        since: object = None,
    ) -> list[IntelligenceNode]:
        with self._session_factory() as session:
            stmt = select(IntelligenceNodeRecord).where(
                IntelligenceNodeRecord.node_type == node_type.value
            )
            if workflow_id is not None:
                stmt = stmt.where(IntelligenceNodeRecord.workflow_id == workflow_id)
            if agent_type is not None:
                stmt = stmt.where(IntelligenceNodeRecord.agent_type == agent_type)
            if task_type is not None:
                stmt = stmt.where(IntelligenceNodeRecord.task_type == task_type)
            if skill_id is not None:
                stmt = stmt.where(IntelligenceNodeRecord.skill_id == skill_id)
            if skill_version is not None:
                stmt = stmt.where(IntelligenceNodeRecord.skill_version == skill_version)
            if since is not None:
                stmt = stmt.where(IntelligenceNodeRecord.created_at >= since)
            stmt = stmt.order_by(IntelligenceNodeRecord.node_id)
            records = session.scalars(stmt).all()
            return [_node_from_record(r) for r in records]

    def get_edges_from(self, node_id: str) -> list[IntelligenceEdge]:
        with self._session_factory() as session:
            stmt = (
                select(IntelligenceEdgeRecord)
                .where(IntelligenceEdgeRecord.source_node_id == node_id)
                .order_by(IntelligenceEdgeRecord.edge_id)
            )
            records = session.scalars(stmt).all()
            return [_edge_from_record(r) for r in records]

    def get_edges_to(self, node_id: str) -> list[IntelligenceEdge]:
        with self._session_factory() as session:
            stmt = (
                select(IntelligenceEdgeRecord)
                .where(IntelligenceEdgeRecord.target_node_id == node_id)
                .order_by(IntelligenceEdgeRecord.edge_id)
            )
            records = session.scalars(stmt).all()
            return [_edge_from_record(r) for r in records]

    def list_failure_attributions(
        self,
        *,
        workflow_id: str | None = None,
        agent_type: str | None = None,
        task_type: str | None = None,
        skill_id: str | None = None,
        category: FailureAttributionCategory | None = None,
        since: object = None,
        limit: int = 100,
    ) -> list[FailureAttribution]:
        with self._session_factory() as session:
            stmt = select(FailureAttributionRecord)
            if workflow_id is not None:
                stmt = stmt.where(FailureAttributionRecord.workflow_id == workflow_id)
            if agent_type is not None:
                stmt = stmt.where(FailureAttributionRecord.agent_type == agent_type)
            if task_type is not None:
                stmt = stmt.where(FailureAttributionRecord.task_type == task_type)
            if skill_id is not None:
                stmt = stmt.where(FailureAttributionRecord.skill_id == skill_id)
            if category is not None:
                stmt = stmt.where(FailureAttributionRecord.category == category.value)
            if since is not None:
                stmt = stmt.where(FailureAttributionRecord.created_at >= since)
            stmt = stmt.order_by(FailureAttributionRecord.created_at.desc()).limit(limit)
            records = session.scalars(stmt).all()
            return [_attribution_from_record(r) for r in records]


__all__ = [
    "InMemoryIntelligenceGraphRepository",
    "IntelligenceGraphRepository",
    "SqlAlchemyIntelligenceGraphRepository",
]
