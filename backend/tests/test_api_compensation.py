"""Tests for the manual compensation API: `POST /workflows/{id}/compensate`.

`client` and `db_session` share the same underlying SQLite file within one
test (both depend on the same function-scoped `db_engine`), so a workflow can
be constructed directly in a state the synchronous engine never leaves
observable via the API alone (e.g. `RUNNING`, `COMPENSATING`), then exercised
through the real HTTP endpoint.
"""

from httpx import AsyncClient
from sqlalchemy.orm import Session

from app.engine.compensation_registry import CompensationRegistry
from app.engine.registry import ExecutorRegistry
from app.models.enums import WorkflowStatus
from tests.support.compensation_handlers import RecordingCompensationHandler
from tests.support.executors import FailingExecutor, RecordingExecutor
from tests.support.workflow_builders import build_workflow_in_status


async def _create_workflow(client: AsyncClient) -> str:
    response = await client.post(
        "/api/v1/workflows",
        json={
            "name": "demo",
            "steps": [
                {
                    "name": "s0",
                    "position": 0,
                    "agent_type": "mock",
                    "compensation_handler": "demo.undo",
                }
            ],
        },
    )
    result: str = response.json()["id"]
    return result


async def _create_workflow_with_one_eligible_step(client: AsyncClient) -> str:
    """A two-step workflow whose first step succeeds (and is eligible for
    compensation) before its second step fails — unlike `_create_workflow`,
    whose single step fails outright and so is never eligible."""
    response = await client.post(
        "/api/v1/workflows",
        json={
            "name": "demo",
            "steps": [
                {
                    "name": "good",
                    "position": 0,
                    "agent_type": "good",
                    "compensation_handler": "demo.undo",
                },
                {"name": "bad", "position": 1, "agent_type": "bad"},
            ],
        },
    )
    result: str = response.json()["id"]
    return result


async def test_failed_workflow_compensation_returns_200(
    client: AsyncClient,
    executor_registry: ExecutorRegistry,
    compensation_registry: CompensationRegistry,
) -> None:
    executor_registry.register("mock", FailingExecutor())
    compensation_registry.register("demo.undo", RecordingCompensationHandler(output={"ok": True}))
    workflow_id = await _create_workflow(client)
    await client.post(f"/api/v1/workflows/{workflow_id}/execute")

    response = await client.post(f"/api/v1/workflows/{workflow_id}/compensate")

    assert response.status_code == 200
    assert response.json()["status"] == "compensated"


async def test_missing_workflow_returns_404(client: AsyncClient) -> None:
    response = await client.post("/api/v1/workflows/does-not-exist/compensate")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "WORKFLOW_NOT_FOUND"


async def test_pending_workflow_returns_409(client: AsyncClient) -> None:
    workflow_id = await _create_workflow(client)

    response = await client.post(f"/api/v1/workflows/{workflow_id}/compensate")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_COMPENSATION_STATE"


async def test_running_workflow_returns_409(client: AsyncClient, db_session: Session) -> None:
    workflow = build_workflow_in_status(
        db_session, workflow_status=WorkflowStatus.RUNNING, steps=[]
    )

    response = await client.post(f"/api/v1/workflows/{workflow.id}/compensate")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_COMPENSATION_STATE"


async def test_succeeded_workflow_returns_409(
    client: AsyncClient, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("mock", RecordingExecutor(output={"ok": True}))
    workflow_id = await _create_workflow(client)
    await client.post(f"/api/v1/workflows/{workflow_id}/execute")

    response = await client.post(f"/api/v1/workflows/{workflow_id}/compensate")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_COMPENSATION_STATE"


async def test_compensating_workflow_returns_409(client: AsyncClient, db_session: Session) -> None:
    workflow = build_workflow_in_status(
        db_session, workflow_status=WorkflowStatus.COMPENSATING, steps=[]
    )

    response = await client.post(f"/api/v1/workflows/{workflow.id}/compensate")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_COMPENSATION_STATE"


async def test_compensated_workflow_returns_409(client: AsyncClient, db_session: Session) -> None:
    workflow = build_workflow_in_status(
        db_session, workflow_status=WorkflowStatus.COMPENSATED, steps=[]
    )

    response = await client.post(f"/api/v1/workflows/{workflow.id}/compensate")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "COMPENSATION_ALREADY_COMPLETED"


async def test_cancelled_workflow_returns_409(client: AsyncClient, db_session: Session) -> None:
    workflow = build_workflow_in_status(
        db_session, workflow_status=WorkflowStatus.CANCELLED, steps=[]
    )

    response = await client.post(f"/api/v1/workflows/{workflow.id}/compensate")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_COMPENSATION_STATE"


async def test_missing_handler_maps_to_503(
    client: AsyncClient, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("good", RecordingExecutor(output={"ok": True}))
    executor_registry.register("bad", FailingExecutor())
    workflow_id = await _create_workflow_with_one_eligible_step(client)
    await client.post(f"/api/v1/workflows/{workflow_id}/execute")

    response = await client.post(f"/api/v1/workflows/{workflow_id}/compensate")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "COMPENSATION_HANDLER_NOT_REGISTERED"


async def test_repeated_compensation_does_not_rerun_completed_handlers(
    client: AsyncClient,
    executor_registry: ExecutorRegistry,
    compensation_registry: CompensationRegistry,
) -> None:
    executor_registry.register("good", RecordingExecutor(output={"ok": True}))
    executor_registry.register("bad", FailingExecutor())
    handler = RecordingCompensationHandler(output={"ok": True})
    compensation_registry.register("demo.undo", handler)
    workflow_id = await _create_workflow_with_one_eligible_step(client)
    await client.post(f"/api/v1/workflows/{workflow_id}/execute")
    await client.post(f"/api/v1/workflows/{workflow_id}/compensate")

    response = await client.post(f"/api/v1/workflows/{workflow_id}/compensate")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "COMPENSATION_ALREADY_COMPLETED"
    assert len(handler.calls) == 1


async def test_existing_workflow_apis_remain_unchanged(client: AsyncClient) -> None:
    response = await client.post("/api/v1/workflows", json={"name": "demo", "steps": []})
    assert response.status_code == 201

    workflow_id = response.json()["id"]
    get_response = await client.get(f"/api/v1/workflows/{workflow_id}")
    assert get_response.status_code == 200

    list_response = await client.get("/api/v1/workflows")
    assert list_response.status_code == 200
