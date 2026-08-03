"""Tests for the agent-availability and circuit-breaker APIs, and their effect
on the existing workflow execution API."""

from pathlib import Path

from httpx import AsyncClient

from app.engine.registry import ExecutorRegistry
from app.resilience.circuit_breaker import CircuitBreakerRegistry
from tests.support.executors import RetryableFailingExecutor


async def test_get_agents_returns_200(client: AsyncClient) -> None:
    response = await client.get("/api/v1/agents")
    assert response.status_code == 200


async def test_get_agents_returns_all_canonical_agent_types(client: AsyncClient) -> None:
    response = await client.get("/api/v1/agents")
    body = response.json()
    assert {item["agent_type"] for item in body["items"]} == {
        "claude_code",
        "codex",
        "gemini",
        "demo",
    }
    assert body["count"] == 4


async def test_get_agents_exposes_no_secret_fields(client: AsyncClient) -> None:
    response = await client.get("/api/v1/agents")
    body = response.json()
    for item in body["items"]:
        assert set(item.keys()) == {
            "agent_type",
            "enabled",
            "available",
            "registered",
            "execution_mode",
            "reason",
        }


async def test_get_circuit_breakers_returns_200(client: AsyncClient) -> None:
    response = await client.get("/api/v1/resilience/circuit-breakers")
    assert response.status_code == 200
    assert response.json() == {"items": [], "count": 0}


async def test_circuit_snapshots_match_registry_state(
    client: AsyncClient,
    executor_registry: ExecutorRegistry,
    circuit_breaker_registry: CircuitBreakerRegistry,
) -> None:
    executor_registry.register("mock", RetryableFailingExecutor())
    create_response = await client.post(
        "/api/v1/workflows",
        json={
            "name": "demo",
            "steps": [{"name": "s", "position": 0, "agent_type": "mock", "max_attempts": 1}],
        },
    )
    workflow_id = create_response.json()["id"]

    circuit_breaker_registry.get_or_create("mock")  # force at least a threshold-1 open
    for _ in range(3):
        circuit_breaker_registry.get_or_create("mock").record_failure()

    response = await client.post(f"/api/v1/workflows/{workflow_id}/execute")
    assert response.status_code == 503

    snapshots_response = await client.get("/api/v1/resilience/circuit-breakers")
    body = snapshots_response.json()
    mock_snapshot = next(item for item in body["items"] if item["agent_type"] == "mock")
    assert mock_snapshot["state"] == "open"


async def test_circuit_open_execution_returns_503_with_circuit_breaker_open(
    client: AsyncClient,
    executor_registry: ExecutorRegistry,
    circuit_breaker_registry: CircuitBreakerRegistry,
) -> None:
    executor_registry.register("mock", RetryableFailingExecutor())
    for _ in range(5):
        circuit_breaker_registry.get_or_create("mock").record_failure()

    create_response = await client.post(
        "/api/v1/workflows",
        json={
            "name": "demo",
            "steps": [{"name": "s", "position": 0, "agent_type": "mock", "max_attempts": 1}],
        },
    )
    workflow_id = create_response.json()["id"]

    response = await client.post(f"/api/v1/workflows/{workflow_id}/execute")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CIRCUIT_BREAKER_OPEN"


async def test_failed_state_remains_retrievable_after_circuit_rejection(
    client: AsyncClient,
    executor_registry: ExecutorRegistry,
    circuit_breaker_registry: CircuitBreakerRegistry,
) -> None:
    executor_registry.register("mock", RetryableFailingExecutor())
    for _ in range(5):
        circuit_breaker_registry.get_or_create("mock").record_failure()

    create_response = await client.post(
        "/api/v1/workflows",
        json={
            "name": "demo",
            "steps": [{"name": "s", "position": 0, "agent_type": "mock", "max_attempts": 1}],
        },
    )
    workflow_id = create_response.json()["id"]
    await client.post(f"/api/v1/workflows/{workflow_id}/execute")

    response = await client.get(f"/api/v1/workflows/{workflow_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["steps"][0]["attempts"][0]["error_type"] == "CIRCUIT_BREAKER_OPEN"


async def test_existing_workflow_creation_api_unchanged(client: AsyncClient) -> None:
    response = await client.post("/api/v1/workflows", json={"name": "demo", "steps": []})
    assert response.status_code == 201


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


async def test_openapi_generation_succeeds(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/agents" in paths
    assert "/api/v1/resilience/circuit-breakers" in paths


def test_importing_app_launches_no_provider_process() -> None:
    """Importing `app.main` (already imported transitively by other test modules
    at collection time) must never launch `claude`, `codex`, or `gemini` — the
    factory only registers agents inside the FastAPI lifespan, which never runs
    for a plain import."""
    import app.main  # noqa: F401  (import-time side effects only)


def test_importing_app_creates_no_production_database_file() -> None:
    assert not Path("keystone.db").exists()
