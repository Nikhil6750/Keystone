"""Tests for the workflow REST API."""

from httpx import AsyncClient

from app.engine.registry import ExecutorRegistry
from tests.support.executors import RecordingExecutor


async def test_create_workflow_returns_201(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/workflows",
        json={
            "name": "demo",
            "input_payload": {"goal": "demo"},
            "steps": [{"name": "step-1", "position": 0, "agent_type": "mock"}],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "demo"
    assert body["status"] == "pending"


async def test_created_steps_are_returned_in_position_order(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/workflows",
        json={
            "name": "demo",
            "steps": [
                {"name": "second", "position": 1, "agent_type": "mock"},
                {"name": "first", "position": 0, "agent_type": "mock"},
            ],
        },
    )

    assert response.status_code == 201
    steps = response.json()["steps"]
    assert [step["name"] for step in steps] == ["first", "second"]


async def test_invalid_workflow_request_returns_422(client: AsyncClient) -> None:
    response = await client.post("/api/v1/workflows", json={"name": "   ", "steps": []})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


async def test_duplicate_positions_return_422(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/workflows",
        json={
            "name": "demo",
            "steps": [
                {"name": "a", "position": 0, "agent_type": "mock"},
                {"name": "b", "position": 0, "agent_type": "mock"},
            ],
        },
    )

    assert response.status_code == 422


async def test_unknown_request_fields_are_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/workflows", json={"name": "demo", "steps": [], "status": "running"}
    )

    assert response.status_code == 422


async def test_retrieving_an_existing_workflow_returns_200(client: AsyncClient) -> None:
    create_response = await client.post("/api/v1/workflows", json={"name": "demo", "steps": []})
    workflow_id = create_response.json()["id"]

    response = await client.get(f"/api/v1/workflows/{workflow_id}")

    assert response.status_code == 200
    assert response.json()["id"] == workflow_id


async def test_retrieving_missing_workflow_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/workflows/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "WORKFLOW_NOT_FOUND"


async def test_listing_workflows_returns_newest_first(client: AsyncClient) -> None:
    for name in ("first", "second", "third"):
        await client.post("/api/v1/workflows", json={"name": name, "steps": []})

    response = await client.get("/api/v1/workflows")

    assert response.status_code == 200
    names = [item["name"] for item in response.json()["items"]]
    assert names == ["third", "second", "first"]


async def test_listing_applies_default_limit(client: AsyncClient) -> None:
    response = await client.get("/api/v1/workflows")

    assert response.status_code == 200
    assert response.json()["count"] == 0


async def test_listing_rejects_limit_below_one(client: AsyncClient) -> None:
    response = await client.get("/api/v1/workflows", params={"limit": 0})

    assert response.status_code == 422


async def test_listing_rejects_limit_above_100(client: AsyncClient) -> None:
    response = await client.get("/api/v1/workflows", params={"limit": 101})

    assert response.status_code == 422


async def test_list_response_count_equals_returned_item_count(client: AsyncClient) -> None:
    for name in ("a", "b", "c"):
        await client.post("/api/v1/workflows", json={"name": name, "steps": []})

    response = await client.get("/api/v1/workflows", params={"limit": 2})

    body = response.json()
    assert body["count"] == len(body["items"]) == 2


async def test_root_and_health_endpoints_remain_unchanged(client: AsyncClient) -> None:
    root_response = await client.get("/")
    health_response = await client.get("/api/v1/health")

    assert root_response.status_code == 200
    assert root_response.json() == {"service": "keystone-backend", "version": "0.1.0"}
    assert health_response.status_code == 200
    assert health_response.json() == {
        "status": "healthy",
        "service": "keystone-backend",
        "version": "0.1.0",
    }


async def test_openapi_schema_generation_succeeds(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    assert "paths" in response.json()


async def test_execute_with_missing_workflow_returns_404(client: AsyncClient) -> None:
    response = await client.post("/api/v1/workflows/does-not-exist/execute")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "WORKFLOW_NOT_FOUND"


async def test_execute_without_registered_executor_returns_503(client: AsyncClient) -> None:
    create_response = await client.post(
        "/api/v1/workflows",
        json={
            "name": "demo",
            "steps": [{"name": "step-1", "position": 0, "agent_type": "unregistered"}],
        },
    )
    workflow_id = create_response.json()["id"]

    response = await client.post(f"/api/v1/workflows/{workflow_id}/execute")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AGENT_EXECUTOR_NOT_REGISTERED"


async def test_execute_on_non_pending_workflow_returns_409(
    client: AsyncClient, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("mock", RecordingExecutor(output={"ok": True}))
    create_response = await client.post(
        "/api/v1/workflows",
        json={"name": "demo", "steps": [{"name": "step-1", "position": 0, "agent_type": "mock"}]},
    )
    workflow_id = create_response.json()["id"]
    first_execute = await client.post(f"/api/v1/workflows/{workflow_id}/execute")
    assert first_execute.status_code == 200

    second_execute = await client.post(f"/api/v1/workflows/{workflow_id}/execute")

    assert second_execute.status_code == 409
    assert second_execute.json()["error"]["code"] == "INVALID_WORKFLOW_STATE"


async def test_execute_succeeds_and_returns_updated_workflow(
    client: AsyncClient, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("mock", RecordingExecutor(output={"ok": True}))
    create_response = await client.post(
        "/api/v1/workflows",
        json={"name": "demo", "steps": [{"name": "step-1", "position": 0, "agent_type": "mock"}]},
    )
    workflow_id = create_response.json()["id"]

    response = await client.post(f"/api/v1/workflows/{workflow_id}/execute")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["steps"][0]["status"] == "succeeded"
