"""Synchronous, sequential workflow execution engine."""

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.engine.context import ExecutionContext
from app.engine.exceptions import InvalidWorkflowStateError, WorkflowNotFoundError
from app.engine.executor import StepExecutionError, StepExecutionRequest
from app.engine.registry import ExecutorNotRegisteredError, ExecutorRegistry
from app.models.enums import AttemptStatus, StepStatus, WorkflowStatus
from app.models.step_attempt import StepAttempt
from app.models.workflow import Workflow
from app.models.workflow_step import WorkflowStep
from app.services import workflow_service

logger = logging.getLogger(__name__)


def _ensure_json_compatible(output: Any) -> dict[str, Any]:
    if not isinstance(output, dict):
        raise StepExecutionError(
            "executor output must be a JSON object", error_type="INVALID_EXECUTOR_OUTPUT"
        )
    try:
        json.dumps(output)
    except (TypeError, ValueError) as exc:
        raise StepExecutionError(
            "executor output is not JSON-serializable", error_type="INVALID_EXECUTOR_OUTPUT"
        ) from exc
    return output


class WorkflowEngine:
    """Executes a workflow's steps sequentially against an executor registry."""

    def __init__(self, db: Session, registry: ExecutorRegistry) -> None:
        self._db = db
        self._registry = registry

    def execute_workflow(self, workflow_id: str) -> Workflow:
        """Run a `PENDING` workflow's steps to completion (or first failure).

        Raises `WorkflowNotFoundError` if the workflow does not exist, and
        `InvalidWorkflowStateError` if it is not `PENDING`. Raises
        `ExecutorNotRegisteredError` if a step's agent type has no registered
        executor. Returns the persisted workflow (SUCCEEDED or FAILED) for any
        other step failure.
        """
        workflow = workflow_service.get_workflow(self._db, workflow_id)
        if workflow is None:
            raise WorkflowNotFoundError(workflow_id)
        if WorkflowStatus(workflow.status) is not WorkflowStatus.PENDING:
            raise InvalidWorkflowStateError(workflow_id, WorkflowStatus(workflow.status))

        logger.info("workflow_execution_started workflow_id=%s", workflow_id)
        workflow = workflow_service.transition_workflow(
            self._db, workflow_id, WorkflowStatus.RUNNING
        )

        context = ExecutionContext(
            workflow_id=workflow.id, workflow_input=dict(workflow.input_payload)
        )
        steps = sorted(workflow.steps, key=lambda s: s.position)

        for step in steps:
            try:
                context = self._execute_step(workflow, step, context)
            except ExecutorNotRegisteredError as exc:
                self._fail_workflow(workflow.id, error_message=str(exc))
                logger.warning(
                    "workflow_execution_failed workflow_id=%s reason=%s", workflow.id, exc
                )
                raise
            except StepExecutionError as exc:
                self._fail_workflow(workflow.id, error_message=str(exc))
                logger.warning(
                    "workflow_execution_failed workflow_id=%s reason=%s", workflow.id, exc
                )
                return self._reload(workflow.id)
            except Exception:
                self._fail_workflow(
                    workflow.id, error_message="an unexpected error occurred during step execution"
                )
                logger.exception(
                    "workflow_execution_failed workflow_id=%s unexpected_error=true", workflow.id
                )
                raise

        return self._succeed_workflow(workflow, steps, context)

    def _execute_step(
        self, workflow: Workflow, step: WorkflowStep, context: ExecutionContext
    ) -> ExecutionContext:
        workflow_service.transition_step(self._db, step.id, StepStatus.RUNNING)
        attempt = workflow_service.create_step_attempt(self._db, step.id)

        logger.info(
            "step_execution_started workflow_id=%s step_id=%s agent_type=%s attempt_number=%s",
            workflow.id,
            step.id,
            step.agent_type,
            attempt.attempt_number,
        )

        try:
            executor = self._registry.get(step.agent_type)
            request = StepExecutionRequest(
                workflow_id=workflow.id,
                step_id=step.id,
                step_name=step.name,
                agent_type=step.agent_type,
                step_input=dict(step.input_payload),
                workflow_input=context.workflow_input,
                previous_step_outputs=context.previous_step_outputs,
            )
            output = _ensure_json_compatible(executor.execute(request))
        except ExecutorNotRegisteredError as exc:
            logger.warning(
                "executor_not_registered workflow_id=%s step_id=%s agent_type=%s",
                workflow.id,
                step.id,
                step.agent_type,
            )
            self._fail_step(
                attempt, step, error_type="AGENT_EXECUTOR_NOT_REGISTERED", error_message=str(exc)
            )
            raise
        except StepExecutionError as exc:
            logger.warning(
                "step_execution_failed workflow_id=%s step_id=%s error_type=%s",
                workflow.id,
                step.id,
                exc.error_type,
            )
            self._fail_step(attempt, step, error_type=exc.error_type, error_message=str(exc))
            raise
        except Exception:
            logger.exception(
                "step_execution_failed workflow_id=%s step_id=%s unexpected_error=true",
                workflow.id,
                step.id,
            )
            self._fail_step(
                attempt,
                step,
                error_type="UNEXPECTED_ERROR",
                error_message="an unexpected error occurred during step execution",
            )
            raise

        workflow_service.complete_step_attempt(
            self._db, attempt.id, status=AttemptStatus.SUCCEEDED, output_payload=output
        )
        updated_step = workflow_service.transition_step(self._db, step.id, StepStatus.SUCCEEDED)
        updated_step.output_payload = output
        self._db.commit()

        logger.info(
            "step_execution_succeeded workflow_id=%s step_id=%s attempt_number=%s",
            workflow.id,
            step.id,
            attempt.attempt_number,
        )
        return context.with_step_output(step.id, output)

    def _fail_step(
        self, attempt: StepAttempt, step: WorkflowStep, *, error_type: str, error_message: str
    ) -> None:
        workflow_service.complete_step_attempt(
            self._db,
            attempt.id,
            status=AttemptStatus.FAILED,
            error_type=error_type,
            error_message=error_message,
        )
        workflow_service.transition_step(self._db, step.id, StepStatus.FAILED)

    def _fail_workflow(self, workflow_id: str, *, error_message: str) -> Workflow:
        workflow_service.transition_workflow(self._db, workflow_id, WorkflowStatus.FAILED)
        return workflow_service.set_workflow_result(
            self._db, workflow_id, error_message=error_message
        )

    def _succeed_workflow(
        self, workflow: Workflow, steps: list[WorkflowStep], context: ExecutionContext
    ) -> Workflow:
        aggregated: dict[str, Any] = {
            "steps": [
                {
                    "step_id": step.id,
                    "name": step.name,
                    "position": step.position,
                    "output": context.previous_step_outputs.get(step.id, {}),
                }
                for step in steps
            ]
        }
        workflow_service.transition_workflow(self._db, workflow.id, WorkflowStatus.SUCCEEDED)
        workflow_service.set_workflow_result(self._db, workflow.id, output_payload=aggregated)
        logger.info("workflow_execution_succeeded workflow_id=%s", workflow.id)
        return self._reload(workflow.id)

    def _reload(self, workflow_id: str) -> Workflow:
        workflow = workflow_service.get_workflow(self._db, workflow_id)
        if workflow is None:
            raise RuntimeError(f"workflow '{workflow_id}' disappeared during execution")
        return workflow
