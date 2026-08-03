"""Saga-style, reverse-order compensation for failed workflows."""

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.audit import service as audit_service
from app.audit.hashing import compute_digest
from app.audit.types import ActorType, AuditEventType
from app.engine.compensation_context import CompensationRequest
from app.engine.compensation_exceptions import (
    CompensationAlreadyCompletedError,
    CompensationError,
    CompensationExecutionError,
    CompensationHandlerNotRegisteredError,
    InvalidCompensationStateError,
)
from app.engine.compensation_registry import CompensationRegistry
from app.engine.exceptions import WorkflowNotFoundError
from app.models.compensation_attempt import CompensationAttempt
from app.models.enums import CompensationAttemptStatus, StepStatus, WorkflowStatus
from app.models.workflow import Workflow
from app.models.workflow_step import WorkflowStep
from app.services import workflow_service

logger = logging.getLogger(__name__)


def _ensure_json_compatible(output: Any) -> dict[str, Any]:
    if not isinstance(output, dict):
        raise CompensationExecutionError("compensation handler output must be a JSON object")
    try:
        json.dumps(output)
    except (TypeError, ValueError) as exc:
        raise CompensationExecutionError(
            "compensation handler output is not JSON-serializable"
        ) from exc
    return output


def _has_handler(step: WorkflowStep) -> bool:
    return bool(step.compensation_handler and step.compensation_handler.strip())


def _step_ref(step: WorkflowStep) -> dict[str, Any]:
    return {"step_id": step.id, "name": step.name, "position": step.position}


class CompensationService:
    """Compensates a `FAILED` workflow's eligible successful steps, in reverse position order.

    A successful step is eligible only if it has a non-blank
    `compensation_handler`; the step that actually failed is never
    compensated (it never succeeded). Eligible steps without a handler are
    reported as `not_configured` rather than silently skipped.
    """

    def __init__(self, db: Session, registry: CompensationRegistry) -> None:
        self._db = db
        self._registry = registry

    def compensate_workflow(self, workflow_id: str) -> Workflow:
        """Compensate `workflow_id`.

        Raises `WorkflowNotFoundError` if it does not exist,
        `CompensationAlreadyCompletedError` if already `COMPENSATED`, and
        `InvalidCompensationStateError` if not `FAILED`. Raises
        `CompensationHandlerNotRegisteredError` if an eligible step's handler
        is not registered (mapped to `503` by the API layer). Returns the
        persisted workflow (`COMPENSATED` or `FAILED`) for a handler
        execution failure.
        """
        workflow = workflow_service.get_workflow(self._db, workflow_id)
        if workflow is None:
            raise WorkflowNotFoundError(workflow_id)

        status = WorkflowStatus(workflow.status)
        if status is WorkflowStatus.COMPENSATED:
            raise CompensationAlreadyCompletedError(workflow_id)
        if status is not WorkflowStatus.FAILED:
            raise InvalidCompensationStateError(workflow_id, status)

        eligible_steps = sorted(
            (
                s
                for s in workflow.steps
                if StepStatus(s.status) is StepStatus.SUCCEEDED and _has_handler(s)
            ),
            key=lambda s: s.position,
            reverse=True,
        )
        not_configured_steps = [
            s
            for s in workflow.steps
            if StepStatus(s.status) is StepStatus.SUCCEEDED and not _has_handler(s)
        ]
        # Every step's own recorded output, for building each handler's context.
        all_step_outputs = {s.id: s.output_payload for s in workflow.steps if s.output_payload}

        logger.info(
            "workflow_compensation_started workflow_id=%s eligible_step_count=%s",
            workflow_id,
            len(eligible_steps),
        )
        workflow_service.transition_workflow(self._db, workflow_id, WorkflowStatus.COMPENSATING)
        audit_service.append_event(
            self._db,
            workflow_id=workflow_id,
            event_type=AuditEventType.WORKFLOW_COMPENSATION_STARTED,
            actor_type=ActorType.SYSTEM,
            actor_id="workflow_engine",
            payload={
                "eligible_step_count": len(eligible_steps),
                "not_configured_step_count": len(not_configured_steps),
            },
        )

        compensated_summaries: list[dict[str, Any]] = []
        for step in eligible_steps:
            try:
                summary = self._compensate_step(workflow, step, all_step_outputs)
            except CompensationHandlerNotRegisteredError:
                self._fail_compensation(
                    workflow_id,
                    compensated_summaries,
                    not_configured_steps,
                    step,
                    "handler not registered",
                )
                raise
            except CompensationExecutionError as exc:
                self._fail_compensation(
                    workflow_id, compensated_summaries, not_configured_steps, step, str(exc)
                )
                return self._reload(workflow_id)
            except Exception:
                self._fail_compensation(
                    workflow_id,
                    compensated_summaries,
                    not_configured_steps,
                    step,
                    "an unexpected error occurred during compensation",
                )
                raise
            compensated_summaries.append(summary)

        summary = {
            "original_workflow_status": "failed",
            "compensated_steps": compensated_summaries,
            "not_configured_steps": [_step_ref(s) for s in not_configured_steps],
            "failed_compensation_step": None,
        }
        workflow_service.transition_workflow(self._db, workflow_id, WorkflowStatus.COMPENSATED)
        workflow_service.set_compensation_summary(self._db, workflow_id, summary)
        audit_service.append_event(
            self._db,
            workflow_id=workflow_id,
            event_type=AuditEventType.WORKFLOW_COMPENSATED,
            actor_type=ActorType.SYSTEM,
            actor_id="workflow_engine",
            payload={"compensated_step_count": len(compensated_summaries)},
        )
        logger.info("workflow_compensation_succeeded workflow_id=%s", workflow_id)
        return self._reload(workflow_id)

    def _compensate_step(
        self, workflow: Workflow, step: WorkflowStep, all_step_outputs: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        handler_name = step.compensation_handler
        if not handler_name:
            raise RuntimeError("_compensate_step called on a step with no compensation handler")

        workflow_service.transition_step(self._db, step.id, StepStatus.COMPENSATING)
        attempt = workflow_service.create_compensation_attempt(
            self._db, step.id, handler_name=handler_name
        )
        logger.info(
            "step_compensation_started workflow_id=%s step_id=%s handler=%s",
            workflow.id,
            step.id,
            handler_name,
        )
        audit_service.append_event(
            self._db,
            workflow_id=workflow.id,
            step_id=step.id,
            compensation_attempt_id=attempt.id,
            event_type=AuditEventType.STEP_COMPENSATION_STARTED,
            actor_type=ActorType.SYSTEM,
            actor_id="workflow_engine",
            payload={"handler_name": handler_name, "position": step.position},
        )
        audit_service.append_event(
            self._db,
            workflow_id=workflow.id,
            step_id=step.id,
            compensation_attempt_id=attempt.id,
            event_type=AuditEventType.COMPENSATION_ATTEMPT_STARTED,
            actor_type=ActorType.SYSTEM,
            actor_id="workflow_engine",
            payload={"handler_name": handler_name, "attempt_number": attempt.attempt_number},
        )

        try:
            handler = self._registry.get(handler_name)
        except CompensationHandlerNotRegisteredError as exc:
            self._fail_attempt_and_step(
                attempt,
                step,
                error_type="COMPENSATION_HANDLER_NOT_REGISTERED",
                error_message=str(exc),
            )
            raise

        try:
            request = CompensationRequest(
                workflow_id=workflow.id,
                step_id=step.id,
                step_name=step.name,
                step_position=step.position,
                agent_type=step.agent_type,
                compensation_handler=handler_name,
                workflow_input=dict(workflow.input_payload),
                step_input=dict(step.input_payload),
                step_output=step.output_payload,
                previous_step_outputs=dict(all_step_outputs),
                original_failure=workflow.error_message,
            )
            output = _ensure_json_compatible(handler.compensate(request))
        except Exception as exc:
            if isinstance(exc, CompensationError):
                error_message = str(exc)
            else:
                logger.exception(
                    "step_compensation_failed workflow_id=%s step_id=%s unexpected_error=true",
                    workflow.id,
                    step.id,
                )
                error_message = "an unexpected error occurred during compensation"
            self._fail_attempt_and_step(
                attempt,
                step,
                error_type="COMPENSATION_EXECUTION_FAILED",
                error_message=error_message,
            )
            raise CompensationExecutionError(error_message) from exc

        workflow_service.complete_compensation_attempt(
            self._db, attempt.id, status=CompensationAttemptStatus.SUCCEEDED, output_payload=output
        )
        workflow_service.transition_step(self._db, step.id, StepStatus.COMPENSATED)
        logger.info(
            "step_compensation_succeeded workflow_id=%s step_id=%s handler=%s",
            workflow.id,
            step.id,
            handler_name,
        )
        audit_service.append_event(
            self._db,
            workflow_id=workflow.id,
            step_id=step.id,
            compensation_attempt_id=attempt.id,
            event_type=AuditEventType.COMPENSATION_ATTEMPT_SUCCEEDED,
            actor_type=ActorType.COMPENSATION_HANDLER,
            actor_id=handler_name,
            payload={"handler_name": handler_name, "output_digest": compute_digest(output)},
        )
        audit_service.append_event(
            self._db,
            workflow_id=workflow.id,
            step_id=step.id,
            compensation_attempt_id=attempt.id,
            event_type=AuditEventType.STEP_COMPENSATED,
            actor_type=ActorType.SYSTEM,
            actor_id="workflow_engine",
            payload={"handler_name": handler_name, "position": step.position},
        )
        return {
            "step_id": step.id,
            "name": step.name,
            "position": step.position,
            "handler": handler_name,
            "status": "compensated",
            "output": output,
        }

    def _fail_attempt_and_step(
        self,
        attempt: CompensationAttempt,
        step: WorkflowStep,
        *,
        error_type: str,
        error_message: str,
    ) -> None:
        workflow_service.complete_compensation_attempt(
            self._db,
            attempt.id,
            status=CompensationAttemptStatus.FAILED,
            error_type=error_type,
            error_message=error_message,
        )
        workflow_service.transition_step(self._db, step.id, StepStatus.FAILED)
        audit_service.append_event(
            self._db,
            workflow_id=step.workflow_id,
            step_id=step.id,
            compensation_attempt_id=attempt.id,
            event_type=AuditEventType.COMPENSATION_ATTEMPT_FAILED,
            actor_type=ActorType.SYSTEM,
            actor_id="workflow_engine",
            payload={"error_type": error_type},
        )
        audit_service.append_event(
            self._db,
            workflow_id=step.workflow_id,
            step_id=step.id,
            compensation_attempt_id=attempt.id,
            event_type=AuditEventType.STEP_COMPENSATION_FAILED,
            actor_type=ActorType.SYSTEM,
            actor_id="workflow_engine",
            payload={"error_type": error_type},
        )

    def _fail_compensation(
        self,
        workflow_id: str,
        compensated_so_far: list[dict[str, Any]],
        not_configured_steps: list[WorkflowStep],
        failed_step: WorkflowStep,
        reason: str,
    ) -> None:
        workflow_service.transition_workflow(self._db, workflow_id, WorkflowStatus.FAILED)
        summary = {
            "original_workflow_status": "failed",
            "compensated_steps": compensated_so_far,
            "not_configured_steps": [_step_ref(s) for s in not_configured_steps],
            "failed_compensation_step": {**_step_ref(failed_step), "reason": reason},
        }
        # Deliberately does not touch workflow.error_message: the original
        # execution failure reason must remain traceable; the compensation
        # failure reason lives only in the summary above.
        workflow_service.set_compensation_summary(self._db, workflow_id, summary)
        audit_service.append_event(
            self._db,
            workflow_id=workflow_id,
            step_id=failed_step.id,
            event_type=AuditEventType.WORKFLOW_COMPENSATION_FAILED,
            actor_type=ActorType.SYSTEM,
            actor_id="workflow_engine",
            payload={"reason": reason, "failed_step_id": failed_step.id},
        )
        logger.warning(
            "workflow_compensation_failed workflow_id=%s failed_step_id=%s reason=%s",
            workflow_id,
            failed_step.id,
            reason,
        )

    def _reload(self, workflow_id: str) -> Workflow:
        workflow = workflow_service.get_workflow(self._db, workflow_id)
        if workflow is None:
            raise RuntimeError(f"workflow '{workflow_id}' disappeared during compensation")
        return workflow
