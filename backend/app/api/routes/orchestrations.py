"""Stage 8C.2: orchestration execution + Server-Sent Events API routes.

`POST` starts a background execution and returns `202 Accepted` immediately
(Part 3) -- it never calls `await service.orchestrate(...)` inline. `GET
.../events` streams `OrchestrationEvent`s as SSE, replaying stored history
first and then following live pushes from the store's bounded per-
connection queue (Part 9/10) -- never a polling loop, never a second
Manager/Workflow run just because a client (re)connects.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.deps import get_orchestration_execution_coordinator, get_orchestration_execution_store
from app.engine.orchestration.errors import OrchestrationExecutionNotFoundError
from app.engine.orchestration.events import OrchestrationEvent
from app.engine.orchestration.execution import (
    OrchestrationExecutionCoordinator,
    OrchestrationExecutionStatus,
    OrchestrationExecutionStore,
)
from app.engine.orchestration.models import OrchestrationRequest
from app.schemas.orchestration import (
    OrchestrationExecutionAccepted,
    OrchestrationExecutionCreate,
    OrchestrationExecutionRead,
    orchestration_execution_create_to_kwargs,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orchestrations", tags=["orchestrations"])

# Bounded keepalive so a genuinely idle-but-still-running connection is not
# silently dropped by an intermediary proxy -- sent only as an SSE comment
# line (never a real event, never affects `sequence`/history).
_HEARTBEAT_SECONDS = 2.5

_TERMINAL_EVENT_TYPES = frozenset(
    {"execution.completed", "execution.failed", "execution.cancelled"}
)


@router.post("", response_model=OrchestrationExecutionAccepted, status_code=202)
async def create_orchestration_execution(
    data: OrchestrationExecutionCreate,
    request: Request,
    coordinator: OrchestrationExecutionCoordinator = Depends(  # noqa: B008
        get_orchestration_execution_coordinator
    ),
) -> OrchestrationExecutionAccepted:
    """Start one orchestration execution. Returns immediately with an
    `execution_id`, never holding the HTTP request open for the pipeline to
    finish (see `app.engine.orchestration.execution` module docstring)."""
    execution_id = data.request_id or uuid.uuid4().hex
    orchestration_request = OrchestrationRequest(
        request_id=execution_id,
        **orchestration_execution_create_to_kwargs(data),
    )
    await coordinator.start(orchestration_request)

    base_url = str(request.url_for("get_orchestration_execution", execution_id=execution_id))
    events_url = str(request.url_for("stream_orchestration_events", execution_id=execution_id))
    return OrchestrationExecutionAccepted(
        execution_id=execution_id,
        status=OrchestrationExecutionStatus.ACCEPTED,
        events_url=events_url,
        result_url=base_url,
    )


@router.get("/{execution_id}", response_model=OrchestrationExecutionRead)
async def get_orchestration_execution(
    execution_id: str,
    store: OrchestrationExecutionStore = Depends(get_orchestration_execution_store),  # noqa: B008
) -> OrchestrationExecutionRead:
    """Return the current safe, observable state of one execution -- job
    status and (once available) business outcome, kept distinct (Part 19)."""
    record = await store.get(execution_id)
    if record is None:
        raise OrchestrationExecutionNotFoundError(execution_id)

    result = record.result
    return OrchestrationExecutionRead(
        execution_id=record.execution_id,
        job_status=record.status,
        orchestration_outcome=result.outcome if result is not None else None,
        workflow_id=result.workflow_id if result is not None else None,
        final_workflow_state=result.final_workflow_state if result is not None else None,
        verification_status=result.verification_status if result is not None else None,
        task_count=result.task_count if result is not None else None,
        selected_agent_types=result.selected_agent_types if result is not None else (),
        attempt_count=result.attempt_count if result is not None else None,
        recovery_used=result.recovery_used if result is not None else None,
        recovery_action=(
            result.recovery_action.value
            if result is not None and result.recovery_action is not None
            else None
        ),
        learning_event_count=(len(result.learning_event_ids) if result is not None else None),
        retrieval_feedback_recorded=(
            result.retrieval_feedback_recorded if result is not None else None
        ),
        issue_codes=result.issue_codes if result is not None else (),
        quality_run_id=result.quality_run_id if result is not None else None,
        quality_verdict_status=result.quality_verdict_status if result is not None else None,
        error_summary=record.error_summary,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _serialize_event(event: OrchestrationEvent) -> str:
    """`id: ...\\nevent: ...\\ndata: {...}\\n\\n` -- standard SSE framing.
    `data` is bounded, typed JSON built only from `OrchestrationEvent`'s own
    already-safe fields (see that module's docstring) -- never a raw
    provider payload, prompt, or stack trace."""
    payload = asdict(event)
    payload["event_type"] = event.event_type.value
    payload["timestamp"] = event.timestamp.isoformat()
    payload["safe_issue_codes"] = list(event.safe_issue_codes)
    data = json.dumps(payload, separators=(",", ":"))
    return f"id: {event.event_id}\nevent: {event.event_type.value}\ndata: {data}\n\n"


async def _event_stream(
    execution_id: str, store: OrchestrationExecutionStore
) -> AsyncIterator[str]:
    record = await store.get(execution_id)
    if record is None:
        raise OrchestrationExecutionNotFoundError(execution_id)

    last_sequence = 0
    async with store.subscribe(execution_id) as queue:
        # Replay first (Part 10): every already-recorded event, in order.
        # Subscribing *before* replay would risk missing nothing (the
        # queue simply buffers anything emitted concurrently); replaying
        # *before* reading the queue is what guarantees no duplicate
        # delivery of an event this connection already replayed.
        for event in await store.get_events(execution_id, after_sequence=0):
            last_sequence = event.sequence
            yield _serialize_event(event)
            if event.event_type.value in _TERMINAL_EVENT_TYPES:
                return

        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECONDS)
            except TimeoutError:
                yield ": heartbeat\n\n"
                continue
            if item is None:
                return
            if item.sequence <= last_sequence:
                continue  # already replayed from history above
            last_sequence = item.sequence
            yield _serialize_event(item)
            if item.event_type.value in _TERMINAL_EVENT_TYPES:
                return


@router.get("/{execution_id}/events")
async def stream_orchestration_events(
    execution_id: str,
    store: OrchestrationExecutionStore = Depends(get_orchestration_execution_store),  # noqa: B008
) -> StreamingResponse:
    """Server-Sent Events stream for one execution's observable progress.
    Never exposes chain-of-thought, raw provider output, prompts, secrets,
    or unrestricted worker output -- see `OrchestrationEvent`'s bounded
    field set."""
    # Validate existence eagerly so an unknown execution_id gets a normal
    # 404 (via the registered exception handler) instead of a 200 response
    # whose body then immediately fails.
    record = await store.get(execution_id)
    if record is None:
        raise OrchestrationExecutionNotFoundError(execution_id)

    return StreamingResponse(
        _event_stream(execution_id, store),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


__all__ = ["router"]
