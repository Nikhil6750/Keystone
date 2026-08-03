"""End-to-end integration tests spanning execution, compensation, and the audit chain.

Uses the `client` fixture for real HTTP-level round trips (creation, execution,
compensation) and `db_session`/`compensation_registry` for direct inspection
and tamper injection — both share the same underlying SQLite file via the
common `db_engine` fixture.
"""

from httpx import AsyncClient
from sqlalchemy.orm import Session

from app.engine.compensation_registry import CompensationRegistry
from app.engine.registry import ExecutorRegistry
from app.models.audit_event import AuditEvent
from tests.support.compensation_handlers import RecordingCompensationHandler
from tests.support.executors import FailingExecutor, RecordingExecutor


async def test_successful_workflow_produces_valid_chain_and_ordered_provenance(
    client: AsyncClient, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("mock", RecordingExecutor(output={"ok": True}))
    create_response = await client.post(
        "/api/v1/workflows",
        json={"name": "demo", "steps": [{"name": "s0", "position": 0, "agent_type": "mock"}]},
    )
    workflow_id = create_response.json()["id"]

    execute_response = await client.post(f"/api/v1/workflows/{workflow_id}/execute")
    assert execute_response.json()["status"] == "succeeded"

    verify_response = await client.get(f"/api/v1/workflows/{workflow_id}/audit-chain/verify")
    assert verify_response.json()["valid"] is True

    provenance_response = await client.get(f"/api/v1/workflows/{workflow_id}/provenance")
    body = provenance_response.json()
    assert body["chain_valid"] is True
    sequence_numbers = [event["sequence_number"] for event in body["events"]]
    assert sequence_numbers == sorted(sequence_numbers)
    assert sequence_numbers == list(range(1, len(sequence_numbers) + 1))


async def test_failed_workflow_then_manual_compensation_produces_valid_chain(
    client: AsyncClient,
    executor_registry: ExecutorRegistry,
    compensation_registry: CompensationRegistry,
) -> None:
    executor_registry.register("good", RecordingExecutor(output={"ok": True}))
    executor_registry.register("bad", FailingExecutor())
    compensation_registry.register(
        "demo.undo", RecordingCompensationHandler(output={"undone": True})
    )
    create_response = await client.post(
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
    workflow_id = create_response.json()["id"]
    await client.post(f"/api/v1/workflows/{workflow_id}/execute")

    compensate_response = await client.post(f"/api/v1/workflows/{workflow_id}/compensate")
    assert compensate_response.json()["status"] == "compensated"

    verify_response = await client.get(f"/api/v1/workflows/{workflow_id}/audit-chain/verify")
    assert verify_response.json()["valid"] is True


async def test_provenance_orders_failure_before_compensation_events(
    client: AsyncClient,
    executor_registry: ExecutorRegistry,
    compensation_registry: CompensationRegistry,
) -> None:
    executor_registry.register("good", RecordingExecutor(output={"ok": True}))
    executor_registry.register("bad", FailingExecutor())
    compensation_registry.register(
        "demo.undo", RecordingCompensationHandler(output={"undone": True})
    )
    create_response = await client.post(
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
    workflow_id = create_response.json()["id"]
    await client.post(f"/api/v1/workflows/{workflow_id}/execute")
    await client.post(f"/api/v1/workflows/{workflow_id}/compensate")

    response = await client.get(f"/api/v1/workflows/{workflow_id}/provenance")
    event_types = [event["event_type"] for event in response.json()["events"]]

    failed_index = event_types.index("workflow_failed")
    compensation_started_index = event_types.index("workflow_compensation_started")
    compensated_index = event_types.index("workflow_compensated")
    assert failed_index < compensation_started_index < compensated_index


async def test_tamper_detection_end_to_end(
    client: AsyncClient, executor_registry: ExecutorRegistry, db_session: Session
) -> None:
    executor_registry.register("mock", RecordingExecutor(output={"ok": True}))
    create_response = await client.post(
        "/api/v1/workflows",
        json={"name": "demo", "steps": [{"name": "s0", "position": 0, "agent_type": "mock"}]},
    )
    workflow_id = create_response.json()["id"]
    await client.post(f"/api/v1/workflows/{workflow_id}/execute")

    before_response = await client.get(f"/api/v1/workflows/{workflow_id}/audit-chain/verify")
    assert before_response.json()["valid"] is True

    tampered_event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.workflow_id == workflow_id)
        .order_by(AuditEvent.sequence_number)
        .offset(1)
        .first()
    )
    assert tampered_event is not None
    tampered_event.payload = {"tampered": True}
    db_session.commit()

    after_response = await client.get(f"/api/v1/workflows/{workflow_id}/audit-chain/verify")
    body = after_response.json()
    assert body["valid"] is False
    assert body["first_invalid_sequence"] == tampered_event.sequence_number


async def test_repeated_compensation_does_not_grow_audit_chain(
    client: AsyncClient,
    executor_registry: ExecutorRegistry,
    compensation_registry: CompensationRegistry,
) -> None:
    executor_registry.register("mock", FailingExecutor())
    compensation_registry.register("demo.undo", RecordingCompensationHandler(output={"ok": True}))
    create_response = await client.post(
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
    workflow_id = create_response.json()["id"]
    await client.post(f"/api/v1/workflows/{workflow_id}/execute")
    await client.post(f"/api/v1/workflows/{workflow_id}/compensate")
    first_count = (await client.get(f"/api/v1/workflows/{workflow_id}/audit-events")).json()[
        "count"
    ]

    second_response = await client.post(f"/api/v1/workflows/{workflow_id}/compensate")
    assert second_response.status_code == 409
    second_count = (await client.get(f"/api/v1/workflows/{workflow_id}/audit-events")).json()[
        "count"
    ]

    assert second_count == first_count


async def test_workflow_with_zero_eligible_steps_compensates_cleanly(
    client: AsyncClient, executor_registry: ExecutorRegistry
) -> None:
    executor_registry.register("mock", FailingExecutor())
    create_response = await client.post(
        "/api/v1/workflows",
        json={"name": "demo", "steps": [{"name": "s0", "position": 0, "agent_type": "mock"}]},
    )
    workflow_id = create_response.json()["id"]
    await client.post(f"/api/v1/workflows/{workflow_id}/execute")

    response = await client.post(f"/api/v1/workflows/{workflow_id}/compensate")

    assert response.status_code == 200
    assert response.json()["compensation_summary"]["compensated_steps"] == []
    verify_response = await client.get(f"/api/v1/workflows/{workflow_id}/audit-chain/verify")
    assert verify_response.json()["valid"] is True


async def test_compensation_attempt_correlates_with_its_audit_event(
    client: AsyncClient,
    executor_registry: ExecutorRegistry,
    compensation_registry: CompensationRegistry,
) -> None:
    executor_registry.register("good", RecordingExecutor(output={"ok": True}))
    executor_registry.register("bad", FailingExecutor())
    compensation_registry.register(
        "demo.undo", RecordingCompensationHandler(output={"undone": True})
    )
    create_response = await client.post(
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
    workflow_id = create_response.json()["id"]
    await client.post(f"/api/v1/workflows/{workflow_id}/execute")
    compensate_response = await client.post(f"/api/v1/workflows/{workflow_id}/compensate")

    good_step = next(step for step in compensate_response.json()["steps"] if step["name"] == "good")
    attempt_id = good_step["compensation_attempts"][0]["id"]

    audit_response = await client.get(f"/api/v1/workflows/{workflow_id}/audit-events")
    correlated = [
        event
        for event in audit_response.json()["items"]
        if event["compensation_attempt_id"] == attempt_id
    ]
    assert len(correlated) >= 1


async def test_full_lifecycle_via_direct_engine_and_compensation_service(
    db_session: Session,
    executor_registry: ExecutorRegistry,
    compensation_registry: CompensationRegistry,
) -> None:
    """Direct-engine round trip covering execution, failure, and compensation
    together, verified through the audit-chain and provenance modules
    directly (no HTTP layer), complementing the API-level tests above."""
    from app.audit.verification import build_provenance, verify_chain
    from app.engine.compensation import CompensationService
    from app.engine.workflow_engine import WorkflowEngine
    from app.resilience.circuit_breaker import CircuitBreakerRegistry
    from app.resilience.retry import RetryPolicy
    from app.schemas.workflow import WorkflowCreate, WorkflowStepCreate
    from app.services import workflow_service
    from tests.support.fakes import FakeSleeper

    executor_registry.register("good", RecordingExecutor(output={"ok": True}))
    executor_registry.register("bad", FailingExecutor())
    compensation_registry.register(
        "demo.undo", RecordingCompensationHandler(output={"undone": True})
    )
    engine = WorkflowEngine(
        db_session,
        executor_registry,
        circuit_breakers=CircuitBreakerRegistry(
            failure_threshold=100, recovery_timeout_seconds=300.0
        ),
        retry_policy=RetryPolicy(base_delay_seconds=0.01, max_delay_seconds=0.05),
        sleeper=FakeSleeper(),
        compensation_registry=compensation_registry,
    )
    workflow = workflow_service.create_workflow(
        db_session,
        WorkflowCreate(
            name="demo",
            input_payload={},
            steps=[
                WorkflowStepCreate(
                    name="good", position=0, agent_type="good", compensation_handler="demo.undo"
                ),
                WorkflowStepCreate(name="bad", position=1, agent_type="bad"),
            ],
        ),
    )

    executed = engine.execute_workflow(workflow.id)
    assert executed.status == "failed"

    compensation_service = CompensationService(db_session, compensation_registry)
    compensated = compensation_service.compensate_workflow(workflow.id)
    assert compensated.status == "compensated"

    verification = verify_chain(db_session, workflow.id)
    assert verification.valid is True

    provenance = build_provenance(db_session, workflow.id)
    assert provenance["chain_valid"] is True
    assert len(provenance["events"]) == verification.event_count
