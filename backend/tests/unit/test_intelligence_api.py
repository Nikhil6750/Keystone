"""Stage 9E: REST API tests -- read-only, cannot forge reliability/failure evidence."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.contracts.intelligence import (
    FailureAttribution,
    FailureAttributionCategory,
    IntelligenceEdge,
    IntelligenceEdgeType,
    IntelligenceNode,
    IntelligenceNodeType,
)
from app.engine.intelligence.graph_repository import InMemoryIntelligenceGraphRepository
from app.engine.intelligence.query_service import EngineeringIntelligenceQueryService
from app.main import app


def _client_with_seeded_graph() -> TestClient:
    repo = InMemoryIntelligenceGraphRepository()
    wf_node = IntelligenceNode(
        node_id="node:workflow:wf1",
        node_type=IntelligenceNodeType.WORKFLOW,
        canonical_id="wf1",
        label="wf1",
        workflow_id="wf1",
    )
    task_node = IntelligenceNode(
        node_id="node:task:t1",
        node_type=IntelligenceNodeType.TASK,
        canonical_id="t1",
        label="task 1",
        workflow_id="wf1",
        agent_type="agent-api",
        task_type="code_generation",
    )
    attempt_node = IntelligenceNode(
        node_id="node:attempt:a1",
        node_type=IntelligenceNodeType.ATTEMPT,
        canonical_id="a1",
        label="attempt #1",
        workflow_id="wf1",
        agent_type="agent-api",
        task_type="code_generation",
        status="succeeded",
        metadata={"attempt_number": 1},
    )
    repo.upsert_node(wf_node)
    repo.upsert_node(task_node)
    repo.upsert_node(attempt_node)
    repo.upsert_edge(
        IntelligenceEdge(
            edge_id="edge:WORKFLOW_CONTAINS_TASK:node:workflow:wf1->node:task:t1",
            edge_type=IntelligenceEdgeType.WORKFLOW_CONTAINS_TASK,
            source_node_id="node:workflow:wf1",
            target_node_id="node:task:t1",
        )
    )
    repo.upsert_edge(
        IntelligenceEdge(
            edge_id="edge:TASK_HAS_ATTEMPT:node:task:t1->node:attempt:a1",
            edge_type=IntelligenceEdgeType.TASK_HAS_ATTEMPT,
            source_node_id="node:task:t1",
            target_node_id="node:attempt:a1",
        )
    )
    repo.upsert_failure_attribution(
        FailureAttribution(
            attribution_id="attr:node:attempt:a1:execution",
            attempt_node_id="node:attempt:a1",
            category=FailureAttributionCategory.TIMEOUT,
            is_known=True,
            explanation="agent timed out",
            evidence_ids=("a1",),
            workflow_id="wf1",
            agent_type="agent-api",
            task_type="code_generation",
            created_at=datetime.now(UTC),
        )
    )

    app.state.intelligence_query_service = EngineeringIntelligenceQueryService(repo)
    return TestClient(app)


def test_get_node_relationships() -> None:
    client = _client_with_seeded_graph()
    resp = client.get("/api/v1/intelligence/nodes/node:task:t1/relationships")
    assert resp.status_code == 200
    body = resp.json()
    assert body["node"]["node_id"] == "node:task:t1"
    edge_types = {e["edge_type"] for e in body["outgoing"]}
    edge_types |= {e["edge_type"] for e in body["incoming"]}
    assert "TASK_HAS_ATTEMPT" in edge_types
    assert "WORKFLOW_CONTAINS_TASK" in edge_types


def test_get_node_relationships_404_for_unknown_node() -> None:
    client = _client_with_seeded_graph()
    resp = client.get("/api/v1/intelligence/nodes/node:does:not:exist/relationships")
    assert resp.status_code == 404


def test_get_task_reliability() -> None:
    client = _client_with_seeded_graph()
    resp = client.get(
        "/api/v1/intelligence/tasks/reliability", params={"task_type": "code_generation"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["attempt_count"] == 1
    assert body["success_count"] == 1
    assert body["sample_size_is_low"] is True


def test_get_agent_reliability() -> None:
    client = _client_with_seeded_graph()
    resp = client.get("/api/v1/intelligence/agents/agent-api/reliability")
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_type"] == "agent-api"
    assert body["observed_executions"] == 1


def test_get_failure_history_and_category_filter() -> None:
    client = _client_with_seeded_graph()
    resp = client.get("/api/v1/intelligence/failures")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["category"] == "timeout"
    assert body[0]["is_known"] is True

    filtered = client.get("/api/v1/intelligence/failures", params={"category": "timeout"})
    assert filtered.status_code == 200
    assert len(filtered.json()) == 1

    empty = client.get("/api/v1/intelligence/failures", params={"category": "recovery_exhaustion"})
    assert empty.status_code == 200
    assert empty.json() == []


def test_get_failure_history_rejects_unknown_category() -> None:
    client = _client_with_seeded_graph()
    resp = client.get("/api/v1/intelligence/failures", params={"category": "not-a-real-category"})
    assert resp.status_code == 400


def test_quality_gate_intelligence_endpoint_returns_zero_counts_when_no_gates() -> None:
    client = _client_with_seeded_graph()
    resp = client.get("/api/v1/intelligence/quality/gates")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_gate_results"] == 0
    assert body["passed_count"] == 0
