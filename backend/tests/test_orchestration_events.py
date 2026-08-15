"""Tests for `app.engine.orchestration.events` and the Stage 8C.2 event
instrumentation added to `EndToEndOrchestrationService.orchestrate()`.

Uses only certified Stage 8A/8C.1 fakes (`FakeManagerModel`,
`RecordingExecutor`, `RICH_SUCCESS_OUTPUT`) -- fully offline, no network.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.contracts.enums import AgentCapability
from app.engine.manager.fake import FakeManagerModel
from app.engine.manager.models import ManagerResponse, ManagerTaskProposal
from app.engine.orchestration.events import (
    NullEventSink,
    OrchestrationEvent,
    OrchestrationEventSequence,
    OrchestrationEventType,
)
from app.engine.orchestration.models import OrchestrationRequest
from app.engine.orchestration.runtime import StaticCandidateProvider
from app.engine.orchestration.service import EndToEndOrchestrationService
from app.engine.registry import ExecutorRegistry
from tests.support.executors import RecordingExecutor
from tests.support.orchestration_fakes import RICH_SUCCESS_OUTPUT, build_candidate


async def test_null_event_sink_is_a_safe_no_op() -> None:
    sink = NullEventSink()
    event = OrchestrationEvent(
        event_id="evt-1",
        execution_id="exec-1",
        sequence=1,
        event_type=OrchestrationEventType.EXECUTION_STARTED,
        timestamp=datetime.now(UTC),
    )
    assert await sink.on_event(event) is None


def test_event_sequence_is_monotonic_starting_at_one() -> None:
    sequence = OrchestrationEventSequence()
    assert [sequence.next() for _ in range(5)] == [1, 2, 3, 4, 5]


@dataclass
class _RecordingEventSink:
    events: list[OrchestrationEvent] = field(default_factory=list)

    async def on_event(self, event: OrchestrationEvent) -> None:
        self.events.append(event)


@dataclass
class _BrokenEventSink:
    """Always raises -- proves a broken sink never affects the business
    result (Part 8: instrumentation is purely observational)."""

    async def on_event(self, event: OrchestrationEvent) -> None:
        raise RuntimeError("simulated sink failure")


def _build_service(db_session: Session, *, sink: object) -> EndToEndOrchestrationService:
    registry = ExecutorRegistry()
    executor = RecordingExecutor(output=dict(RICH_SUCCESS_OUTPUT))
    registry.register("claude_code", executor)
    candidate_provider = StaticCandidateProvider(agents=(build_candidate("claude_code"),))

    manager_response = ManagerResponse(
        request_id="evt-test-req",
        provider_identifier="fake-manager-events-test",
        task_proposals=[
            ManagerTaskProposal(
                key="t1", description="do it", preferred_agent_types=["claude_code"]
            )
        ],
    )
    manager_model = FakeManagerModel(response=manager_response)

    return EndToEndOrchestrationService(
        db=db_session,
        registry=registry,
        candidate_provider=candidate_provider,
        manager_model=manager_model,
        event_sink=sink,  # type: ignore[arg-type]
    )


def _request() -> OrchestrationRequest:
    return OrchestrationRequest(
        request_id="evt-test-req",
        goal="Implement user authentication with tests",
        available_agent_types=["claude_code"],
        available_capabilities=[AgentCapability.CODE_GENERATION],
    )


async def test_default_event_sink_does_not_change_the_result(db_session: Session) -> None:
    """No `event_sink=` passed at all -- must behave byte-for-byte like a
    plain Stage 8C.1 call (Part 16/24: instrumentation must not change the
    existing, already-certified result)."""
    registry = ExecutorRegistry()
    executor = RecordingExecutor(output=dict(RICH_SUCCESS_OUTPUT))
    registry.register("claude_code", executor)
    candidate_provider = StaticCandidateProvider(agents=(build_candidate("claude_code"),))
    manager_response = ManagerResponse(
        request_id="evt-test-req",
        provider_identifier="fake-manager-events-test",
        task_proposals=[
            ManagerTaskProposal(
                key="t1", description="do it", preferred_agent_types=["claude_code"]
            )
        ],
    )
    service = EndToEndOrchestrationService(
        db=db_session,
        registry=registry,
        candidate_provider=candidate_provider,
        manager_model=FakeManagerModel(response=manager_response),
    )
    result = await service.orchestrate(_request())
    assert result.outcome.value == "verified_success"


async def test_verified_success_run_emits_expected_event_sequence(db_session: Session) -> None:
    sink = _RecordingEventSink()
    service = _build_service(db_session, sink=sink)
    result = await service.orchestrate(_request())

    assert result.outcome.value == "verified_success"

    event_types = [event.event_type for event in sink.events]
    assert event_types == [
        OrchestrationEventType.EXECUTION_STARTED,
        OrchestrationEventType.KNOWLEDGE_STARTED,
        OrchestrationEventType.KNOWLEDGE_COMPLETED,
        OrchestrationEventType.MANAGER_STARTED,
        OrchestrationEventType.MANAGER_COMPLETED,
        OrchestrationEventType.PLANNING_COMPLETED,
        OrchestrationEventType.ROUTING_STARTED,
        OrchestrationEventType.ROUTING_TASK_SELECTED,
        OrchestrationEventType.AGENT_SELECTED,
        OrchestrationEventType.ROUTING_TASK_SELECTED,
        OrchestrationEventType.AGENT_SELECTED,
        OrchestrationEventType.ROUTING_TASK_SELECTED,
        OrchestrationEventType.AGENT_SELECTED,
        OrchestrationEventType.WORKFLOW_CREATED,
        OrchestrationEventType.WORKFLOW_STARTED,
        OrchestrationEventType.STEP_STARTED,
        OrchestrationEventType.TASK_WAITING,
        OrchestrationEventType.TASK_WAITING,
        OrchestrationEventType.STEP_COMPLETED,
        OrchestrationEventType.STEP_STARTED,
        OrchestrationEventType.STEP_COMPLETED,
        OrchestrationEventType.STEP_STARTED,
        OrchestrationEventType.STEP_COMPLETED,
        OrchestrationEventType.VERIFICATION_STARTED,
        OrchestrationEventType.VERIFICATION_COMPLETED,
        OrchestrationEventType.RETRIEVAL_FEEDBACK_COMPLETED,
        OrchestrationEventType.EXECUTION_COMPLETED,
    ]


async def test_event_sequence_numbers_are_unique_and_ordered(db_session: Session) -> None:
    sink = _RecordingEventSink()
    service = _build_service(db_session, sink=sink)
    await service.orchestrate(_request())

    sequences = [event.sequence for event in sink.events]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)
    assert sequences[0] == 1


async def test_event_ids_are_unique(db_session: Session) -> None:
    sink = _RecordingEventSink()
    service = _build_service(db_session, sink=sink)
    await service.orchestrate(_request())

    event_ids = [event.event_id for event in sink.events]
    assert len(set(event_ids)) == len(event_ids)


async def test_terminal_event_emitted_exactly_once(db_session: Session) -> None:
    sink = _RecordingEventSink()
    service = _build_service(db_session, sink=sink)
    await service.orchestrate(_request())

    terminal_types = {
        OrchestrationEventType.EXECUTION_COMPLETED,
        OrchestrationEventType.EXECUTION_FAILED,
        OrchestrationEventType.EXECUTION_CANCELLED,
    }
    terminal_events = [event for event in sink.events if event.event_type in terminal_types]
    assert len(terminal_events) == 1
    assert terminal_events[0].event_type == OrchestrationEventType.EXECUTION_COMPLETED


async def test_routing_task_selected_carries_the_selected_agent_id(db_session: Session) -> None:
    sink = _RecordingEventSink()
    service = _build_service(db_session, sink=sink)
    await service.orchestrate(_request())

    routing_events = [
        event
        for event in sink.events
        if event.event_type == OrchestrationEventType.ROUTING_TASK_SELECTED
    ]
    assert routing_events
    assert all(event.agent_id == "claude_code" for event in routing_events)
    assert all(event.task_key is not None for event in routing_events)


async def test_verification_completed_carries_passed_status(db_session: Session) -> None:
    sink = _RecordingEventSink()
    service = _build_service(db_session, sink=sink)
    await service.orchestrate(_request())

    verification_completed = next(
        event
        for event in sink.events
        if event.event_type == OrchestrationEventType.VERIFICATION_COMPLETED
    )
    assert verification_completed.verification_status == "passed"


async def test_broken_event_sink_never_changes_the_business_result(db_session: Session) -> None:
    """A sink that always raises must not turn a verified success into a
    failure, and must not prevent the run from completing (Part 8)."""
    service = _build_service(db_session, sink=_BrokenEventSink())
    result = await service.orchestrate(_request())
    assert result.outcome.value == "verified_success"


async def test_no_reasoning_or_secret_shaped_fields_on_event_dataclass() -> None:
    """Structural guarantee (Part 6): `OrchestrationEvent` has no untyped
    payload/dict escape hatch through which chain-of-thought, a raw
    provider response, or a secret could be smuggled."""
    field_names = {f for f in OrchestrationEvent.__dataclass_fields__}
    forbidden_substrings = (
        "reasoning",
        "chain_of_thought",
        "prompt",
        "api_key",
        "authorization",
        "raw_response",
        "stdout",
        "stderr",
        "payload",
    )
    for name in field_names:
        for forbidden in forbidden_substrings:
            assert forbidden not in name.lower(), f"unexpected field name: {name}"
