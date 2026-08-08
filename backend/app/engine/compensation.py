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
    CompensationResumeConflictError,
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

    def resume_compensation(self, workflow_id: str) -> Workflow:
        """Resume compensation for a workflow left `COMPENSATING` by a
        process interruption.

        Raises `WorkflowNotFoundError` if the workflow does not exist,
        `InvalidCompensationStateError` if it is not `COMPENSATING`, and
        `CompensationResumeConflictError` if another compensation-resume is
        already in progress (an atomic optimistic check on `Workflow.version`,
        identical in spirit to `WorkflowEngine.resume_workflow`'s own claim).

        A step already `COMPENSATED` is never compensated again. The one step
        (if any) whose handler was still running when the process was
        interrupted has its dangling `CompensationAttempt` marked `FAILED`
        first — never assumed to have silently succeeded — and is then
        re-attempted with a fresh attempt. Remaining eligible steps continue
        in the same reverse-position order a fresh `compensate_workflow` run
        would use. The returned summary is rebuilt from current persisted
        step state, not from any in-memory list from the interrupted run
        (which is lost — nothing about the crashed process's local variables
        survives a restart); each already-compensated step's summary entry
        is reconstructed from its own successful `CompensationAttempt` row.
        """
        workflow = workflow_service.get_workflow(self._db, workflow_id)
        if workflow is None:
            raise WorkflowNotFoundError(workflow_id)

        status = WorkflowStatus(workflow.status)
        if status is not WorkflowStatus.COMPENSATING:
            raise InvalidCompensationStateError(workflow_id, status)

        claimed = workflow_service.claim_workflow_for_compensation_resume(
            self._db, workflow_id, expected_version=workflow.version
        )
        if not claimed:
            raise CompensationResumeConflictError(workflow_id)
        workflow = self._reload(workflow_id)

        logger.info("workflow_compensation_resume_started workflow_id=%s", workflow_id)

        all_step_outputs = {s.id: s.output_payload for s in workflow.steps if s.output_payload}
        interrupted_steps = sorted(
            (s for s in workflow.steps if StepStatus(s.status) is StepStatus.COMPENSATING),
            key=lambda s: s.position,
            reverse=True,
        )
        remaining_eligible_steps = sorted(
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
        already_compensated_steps = sorted(
            (s for s in workflow.steps if StepStatus(s.status) is StepStatus.COMPENSATED),
            key=lambda s: s.position,
            reverse=True,
        )

        audit_service.append_event(
            self._db,
            workflow_id=workflow_id,
            event_type=AuditEventType.WORKFLOW_COMPENSATION_RESUMED,
            actor_type=ActorType.SYSTEM,
            actor_id="workflow_engine",
            payload={
                "already_compensated_step_ids": [s.id for s in already_compensated_steps],
                "interrupted_step_ids": [s.id for s in interrupted_steps],
                "remaining_step_ids": [s.id for s in remaining_eligible_steps],
            },
        )

        compensated_summaries: list[dict[str, Any]] = [
            self._reconstruct_compensated_summary(s) for s in already_compensated_steps
        ]

        for step in interrupted_steps:
            self._mark_interrupted_compensation_attempt_failed(step)
            handler_name = step.compensation_handler
            if not handler_name:
                # Unreachable in practice: a step cannot reach COMPENSATING
                # without a handler name (see _compensate_step). Guarded
                # explicitly rather than asserted away.
                raise RuntimeError(
                    f"step '{step.id}' is COMPENSATING but has no compensation_handler"
                )
            try:
                summary = self._run_compensation_attempt(
                    workflow, step, all_step_outputs, handler_name
                )
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

        for step in remaining_eligible_steps:
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
        logger.info("workflow_compensation_resume_succeeded workflow_id=%s", workflow_id)
        return self._reload(workflow_id)

    def _mark_interrupted_compensation_attempt_failed(self, step: WorkflowStep) -> None:
        """Mark a step's dangling `RUNNING` compensation attempt `FAILED`
        before resume re-attempts it. Never assumes the interrupted handler
        call actually failed — only that this process can no longer observe
        its outcome, so it must not be trusted as completed. Mirrors
        `WorkflowEngine._mark_interrupted_attempt_failed` exactly, for
        compensation attempts instead of execution attempts."""
        if not step.compensation_attempts:
            return
        latest = max(step.compensation_attempts, key=lambda attempt: attempt.attempt_number)
        if CompensationAttemptStatus(latest.status) is not CompensationAttemptStatus.RUNNING:
            return
        workflow_service.complete_compensation_attempt(
            self._db,
            latest.id,
            status=CompensationAttemptStatus.FAILED,
            error_type="EXECUTION_INTERRUPTED",
            error_message="compensation attempt was in-flight when the process was interrupted",
        )
        audit_service.append_event(
            self._db,
            workflow_id=step.workflow_id,
            step_id=step.id,
            compensation_attempt_id=latest.id,
            event_type=AuditEventType.COMPENSATION_ATTEMPT_FAILED,
            actor_type=ActorType.SYSTEM,
            actor_id="workflow_engine",
            payload={"error_type": "EXECUTION_INTERRUPTED", "reason": "process_interrupted"},
        )

    @staticmethod
    def _reconstruct_compensated_summary(step: WorkflowStep) -> dict[str, Any]:
        """Rebuild one already-`COMPENSATED` step's summary entry from its own
        persisted `CompensationAttempt` history — the only durable record of
        it, since an interrupted run's in-memory summary list never survives
        a process restart."""
        successful_attempt = max(
            (
                attempt
                for attempt in step.compensation_attempts
                if CompensationAttemptStatus(attempt.status) is CompensationAttemptStatus.SUCCEEDED
            ),
            key=lambda attempt: attempt.attempt_number,
            default=None,
        )
        return {
            "step_id": step.id,
            "name": step.name,
            "position": step.position,
            "handler": step.compensation_handler,
            "status": "compensated",
            "output": successful_attempt.output_payload if successful_attempt else None,
        }

    def _compensate_step(
        self, workflow: Workflow, step: WorkflowStep, all_step_outputs: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        """Compensate a freshly-eligible (`SUCCEEDED`) step: transitions it to
        `COMPENSATING` first, then runs the attempt. For a step already
        `COMPENSATING` (resumed after an interruption mid-handler-call), see
        `resume_compensation`, which calls `_run_compensation_attempt`
        directly instead — `COMPENSATING` has no legal transition back to
        itself, so this transition must not be repeated."""
        handler_name = step.compensation_handler
        if not handler_name:
            raise RuntimeError("_compensate_step called on a step with no compensation handler")
        workflow_service.transition_step(self._db, step.id, StepStatus.COMPENSATING)
        return self._run_compensation_attempt(workflow, step, all_step_outputs, handler_name)

    def _run_compensation_attempt(
        self,
        workflow: Workflow,
        step: WorkflowStep,
        all_step_outputs: dict[str, dict[str, Any]],
        handler_name: str,
    ) -> dict[str, Any]:
        """Create and run one compensation attempt for `step`, which must
        already be in `COMPENSATING` status. Shared by `_compensate_step`
        (fresh compensation) and `resume_compensation` (a step whose handler
        was already in flight when the process was interrupted)."""
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
