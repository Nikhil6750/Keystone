"""Tests for the audit-events, audit-chain verification, and provenance APIs."""

from httpx import AsyncClient
from sqlalchemy.orm import Session

from app.engine.registry import ExecutorRegistry
from app.models.audit_event import AuditEvent
from tests.support.executors import RecordingExecutor


async def _create_workflow(client: AsyncClient, *, with_step: bool = False) -> str:
    steps = [{"name": "s0", "position": 0, "agent_type": "mock"}] if with_step else []
    response = await client.post("/api/v1/workflows", json={"name": "demo", "steps": steps})
    result: str = response.json()["id"]
    return result


async def test_audit_events_missing_workflow_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/workflows/does-not-exist/audit-events")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "WORKFLOW_NOT_FOUND"


async def test_audit_events_returns_events_in_sequence_order(client: AsyncClient) -> None:
    workflow_id = await _create_workflow(client)

    response = await client.get(f"/api/v1/workflows/{workflow_id}/audit-events")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] >= 1
    sequence_numbers = [item["sequence_number"] for item in body["items"]]
    assert sequence_numbers == sorted(sequence_numbers)


async def test_creating_workflow_appends_workflow_created_event(client: AsyncClient) -> None:
    workflow_id = await _create_workflow(client)

    response = await client.get(f"/api/v1/workflows/{workflow_id}/audit-events")

    event_types = [item["event_type"] for item in response.json()["items"]]
    assert "workflow_created" in event_types


async def test_audit_events_respects_limit_query_param(client: AsyncClient) -> None:
    workflow_id = await _create_workflow(client)

    response = await client.get(
        f"/api/v1/workflows/{workflow_id}/audit-events", params={"limit": 1}
    )

    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


async def test_audit_events_limit_below_minimum_returns_422(client: AsyncClient) -> None:
    workflow_id = await _create_workflow(client)

    response = await client.get(
        f"/api/v1/workflows/{workflow_id}/audit-events", params={"limit": 0}
    )

    assert response.status_code == 422


async def test_audit_events_limit_above_maximum_returns_422(client: AsyncClient) -> None:
    workflow_id = await _create_workflow(client)

    response = await client.get(
        f"/api/v1/workflows/{workflow_id}/audit-events", params={"limit": 501}
    )

    assert response.status_code == 422


async def test_verify_missing_workflow_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/workflows/does-not-exist/audit-chain/verify")

    assert response.status_code == 404


async def test_verify_untampered_chain_returns_valid_true(client: AsyncClient) -> None:
    workflow_id = await _create_workflow(client)

    response = await client.get(f"/api/v1/workflows/{workflow_id}/audit-chain/verify")

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["first_invalid_sequence"] is None


async def test_verify_tampered_chain_returns_valid_false_with_200(
    client: AsyncClient, db_session: Session
) -> None:
    workflow_id = await _create_workflow(client)
    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.workflow_id == workflow_id)
        .order_by(AuditEvent.sequence_number)
        .first()
    )
    assert event is not None
    event.payload = {"tampered": True}
    db_session.commit()

    response = await client.get(f"/api/v1/workflows/{workflow_id}/audit-chain/verify")

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert body["first_invalid_sequence"] == event.sequence_number


async def test_provenance_missing_workflow_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/workflows/does-not-exist/provenance")

    assert response.status_code == 404


async def test_provenance_returns_workflow_id_chain_valid_and_events(client: AsyncClient) -> None:
    workflow_id = await _create_workflow(client)

    response = await client.get(f"/api/v1/workflows/{workflow_id}/provenance")

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_id"] == workflow_id
    assert body["chain_valid"] is True
    assert isinstance(body["events"], list)
    assert len(body["events"]) >= 1


async def test_provenance_reflects_full_execution_lifecycle(
    client: AsyncClient, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("mock", RecordingExecutor(output={"ok": True}))
    workflow_id = await _create_workflow(client, with_step=True)
    await client.post(f"/api/v1/workflows/{workflow_id}/execute")

    response = await client.get(f"/api/v1/workflows/{workflow_id}/provenance")

    body = response.json()
    event_types = {item["event_type"] for item in body["events"]}
    assert "workflow_succeeded" in event_types
    assert "step_succeeded" in event_types
    assert body["chain_valid"] is True
