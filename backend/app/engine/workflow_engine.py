"""Synchronous, sequential workflow execution engine with retry, circuit-breaker,
and optional automatic compensation support."""

import json
import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.audit import service as audit_service
from app.audit.hashing import compute_digest
from app.audit.types import ActorType, AuditEventType
from app.contracts.enums import AgentExecutionStatus
from app.contracts.errors import FailureCategory
from app.contracts.verification import VerificationStatus
from app.engine.compensation import CompensationService
from app.engine.compensation_registry import CompensationRegistry
from app.engine.context import ExecutionContext
from app.engine.exceptions import (
    InvalidWorkflowStateError,
    WorkflowNotFoundError,
    WorkflowResumeConflictError,
)
from app.engine.executor import StepExecutionError, StepExecutionRequest
from app.engine.registry import ExecutorNotRegisteredError, ExecutorRegistry
from app.models.enums import AttemptStatus, StepStatus, WorkflowStatus
from app.models.step_attempt import StepAttempt
from app.models.workflow import Workflow
from app.models.workflow_step import WorkflowStep
from app.persistence.service import LearningPersistenceService
from app.resilience.circuit_breaker import (
    CircuitBreakerOpenError,
    CircuitBreakerRegistry,
    CircuitState,
)
from app.resilience.retry import RetryPolicy
from app.resilience.sleeper import RealSleeper, Sleeper
from app.services import workflow_service

logger = logging.getLogger(__name__)

_DEFAULT_FAILURE_THRESHOLD = 3
_DEFAULT_RECOVERY_TIMEOUT_SECONDS = 30.0
_DEFAULT_RETRY_BASE_DELAY_SECONDS = 0.5
_DEFAULT_RETRY_MAX_DELAY_SECONDS = 5.0

_SYSTEM_ACTOR = "workflow_engine"

# `StepExecutionError.error_type` values this engine itself raises with,
# mapped to the canonical `FailureCategory` they represent. Deliberately
# not exhaustive of every possible executor-supplied `error_type` -- see
# `_classify_failed_attempt` for the fallback behavior for values outside
# this table.
_ERROR_TYPE_TO_FAILURE_CATEGORY: dict[str, FailureCategory] = {
    "AGENT_EXECUTOR_NOT_REGISTERED": FailureCategory.INTERNAL_ERROR,
    "CIRCUIT_BREAKER_OPEN": FailureCategory.CIRCUIT_OPEN,
    "UNEXPECTED_ERROR": FailureCategory.INTERNAL_ERROR,
    "INVALID_EXECUTOR_OUTPUT": FailureCategory.VALIDATION_FAILURE,
}

# A verification-outcome seam a caller may inject: given the step and the
# attempt that just concluded, return the `VerificationStatus` Stage 4E (or
# a future Stage 8 orchestrator) already determined for it, or `None` if no
# verification has happened yet. Never called by anything in this module
# for a non-terminal (still-retrying) attempt -- only for an attempt that
# is about to produce its step's *final* `LearningEvent`.
VerificationResolver = Callable[[WorkflowStep, StepAttempt], VerificationStatus | None]


def _classify_failed_attempt(
    error_type: str | None,
) -> tuple[AgentExecutionStatus, FailureCategory]:
    """Map one step attempt's `error_type` string to the canonical
    `(AgentExecutionStatus, FailureCategory)` pair its `LearningEvent`
    requires.

    Single-event classification only -- no counting, no rate, no
    percentile; this is not a learning aggregation formula, just the
    typed-enum equivalent of the untyped `error_type` string already on
    `StepAttempt`. An `error_type` this function does not recognize (by
    exact match against this engine's own known constants, by containing
    "TIMEOUT"/"CANCEL", or by matching a `FailureCategory` value directly)
    is reported as `FailureCategory.UNKNOWN` -- never a guessed, more
    specific category nothing actually observed.
    """
    if error_type is None:
        return AgentExecutionStatus.FAILED, FailureCategory.UNKNOWN

    normalized = error_type.strip().upper()
    if normalized in _ERROR_TYPE_TO_FAILURE_CATEGORY:
        return AgentExecutionStatus.FAILED, _ERROR_TYPE_TO_FAILURE_CATEGORY[normalized]
    if "TIMEOUT" in normalized:
        return AgentExecutionStatus.TIMED_OUT, FailureCategory.TIMEOUT
    if "CANCEL" in normalized:
        return AgentExecutionStatus.CANCELLED, FailureCategory.CANCELLED

    try:
        return AgentExecutionStatus.FAILED, FailureCategory(error_type.strip().lower())
    except ValueError:
        return AgentExecutionStatus.FAILED, FailureCategory.UNKNOWN


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
    """Executes a workflow's steps sequentially against an executor registry.

    Retries a step whose failure is marked `retryable` (see `StepExecutionError`)
    while it has attempts remaining and its circuit breaker permits another
    call; otherwise it fails the step and workflow immediately, exactly as in
    Phase 2. `circuit_breakers` and `retry_policy` default to conservative
    built-in settings so the Phase 2 two-argument constructor call keeps
    working. Every execution milestone is recorded in the workflow's audit
    chain (see `app.audit`). When `auto_compensate_on_failure` is `True` and a
    `compensation_registry` is provided, a workflow that reaches `FAILED`
    (other than from an unexpected internal error) is automatically
    compensated through the same `CompensationService` manual compensation
    uses — best-effort: a failure during automatic compensation is logged,
    not re-raised, since `CompensationService` already persists that failure
    durably before any exception would propagate here.

    When `learning_persistence` is supplied, every terminal step attempt
    (success, terminal failure, or a failed-but-retrying attempt) is
    recorded as a `LearningEvent` through it -- see
    `app.persistence.service.LearningPersistenceService.record_step_attempt_outcome`,
    the sole construction point; this class never builds a `LearningEvent`
    itself. `learning_persistence=None` (the default) fully preserves
    Phase 2/3/4 behavior: no learning event is ever recorded, and every
    existing `WorkflowEngine` constructor call keeps working unchanged.
    """

    def __init__(
        self,
        db: Session,
        registry: ExecutorRegistry,
        *,
        circuit_breakers: CircuitBreakerRegistry | None = None,
        retry_policy: RetryPolicy | None = None,
        sleeper: Sleeper | None = None,
        compensation_registry: CompensationRegistry | None = None,
        auto_compensate_on_failure: bool = False,
        learning_persistence: LearningPersistenceService | None = None,
        verification_resolver: VerificationResolver | None = None,
        workspace_root: str | None = None,
    ) -> None:
        self._db = db
        self._db_lock = threading.RLock()
        self._registry = registry
        self._workspace_root = workspace_root
        self._circuit_breakers = circuit_breakers or CircuitBreakerRegistry(
            failure_threshold=_DEFAULT_FAILURE_THRESHOLD,
            recovery_timeout_seconds=_DEFAULT_RECOVERY_TIMEOUT_SECONDS,
        )
        self._retry_policy = retry_policy or RetryPolicy(
            base_delay_seconds=_DEFAULT_RETRY_BASE_DELAY_SECONDS,
            max_delay_seconds=_DEFAULT_RETRY_MAX_DELAY_SECONDS,
        )
        self._sleeper = sleeper or RealSleeper()
        self._auto_compensate_on_failure = auto_compensate_on_failure
        self._compensation_service = (
            CompensationService(db, compensation_registry)
            if compensation_registry is not None
            else None
        )
        self._learning_persistence = learning_persistence
        self._verification_resolver = verification_resolver

    def _record_step_learning_event(
        self,
        step: WorkflowStep,
        attempt: StepAttempt,
        *,
        execution_status: AgentExecutionStatus,
        failure_category: FailureCategory | None = None,
        is_terminal: bool,
        db: Session | None = None,
    ) -> None:
        if self._learning_persistence is None:
            return

        use_db = db or self._db
        verification_status: VerificationStatus | None = None
        if is_terminal and self._verification_resolver is not None:
            verification_status = self._verification_resolver(step, attempt)

        duration_ms: float | None = None
        if attempt.started_at is not None and attempt.completed_at is not None:
            st = attempt.started_at
            ct = attempt.completed_at
            if st.tzinfo is None and ct.tzinfo is not None:
                st = st.replace(tzinfo=UTC)
            elif ct.tzinfo is None and st.tzinfo is not None:
                ct = ct.replace(tzinfo=UTC)
            duration_ms = (ct - st).total_seconds() * 1000.0

        created_at = attempt.completed_at or datetime.now(UTC)
        task_type = step.input_payload.get("task_type") if step.input_payload else None
        repository_id = step.input_payload.get("repository_id") if step.input_payload else None

        try:
            self._learning_persistence.record_step_attempt_outcome(
                use_db,
                workflow_id=step.workflow_id,
                step_id=step.id,
                attempt_number=attempt.attempt_number,
                agent_type=step.agent_type,
                execution_status=execution_status,
                verification_status=verification_status,
                failure_category=failure_category,
                task_type=task_type if isinstance(task_type, str) else None,
                repository_id=repository_id if isinstance(repository_id, str) else None,
                duration_ms=duration_ms,
                created_at=created_at,
            )
            use_db.commit()
        except Exception:
            use_db.rollback()
            logger.exception(
                "learning_event_persistence_failed workflow_id=%s step_id=%s attempt_number=%s",
                step.workflow_id,
                step.id,
                attempt.attempt_number,
            )
            raise

    def execute_workflow(self, workflow_id: str) -> Workflow:
        """Run a `PENDING` workflow's steps to completion (or first failure).

        Raises `WorkflowNotFoundError` if the workflow does not exist,
        `InvalidWorkflowStateError` if it is not `PENDING`,
        `ExecutorNotRegisteredError` if a step's agent type has no registered
        executor, and `CircuitBreakerOpenError` if a step's circuit is open.
        Returns the persisted workflow (SUCCEEDED or FAILED) for any other
        step failure.
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
        audit_service.append_event(
            self._db,
            workflow_id=workflow_id,
            event_type=AuditEventType.WORKFLOW_EXECUTION_STARTED,
            actor_type=ActorType.SYSTEM,
            actor_id=_SYSTEM_ACTOR,
            payload={"step_count": len(workflow.steps)},
        )

        context = ExecutionContext(
            workflow_id=workflow.id, workflow_input=dict(workflow.input_payload)
        )
        steps = sorted(workflow.steps, key=lambda s: s.position)

        return self._run_to_completion(workflow, steps, steps, context)

    async def execute_workflow_async(
        self,
        workflow_id: str,
        task_nodes: list[Any] | None = None,
        context: ExecutionContext | None = None,
        workspace_watcher: Any = None,
        max_concurrency: int = 3,
    ) -> tuple[Workflow, dict[str, dict[str, datetime]]]:
        """Execute task graph concurrently using asyncio with real multi-agent parallelization."""
        import asyncio

        workflow = workflow_service.get_workflow(self._db, workflow_id)
        if workflow is None:
            raise WorkflowNotFoundError(workflow_id)
        if WorkflowStatus(workflow.status) is not WorkflowStatus.RUNNING:
            workflow = workflow_service.transition_workflow(
                self._db, workflow_id, WorkflowStatus.RUNNING
            )

        if context is None:
            context = ExecutionContext(
                workflow_id=workflow.id, workflow_input=dict(workflow.input_payload)
            )

        steps = sorted(workflow.steps, key=lambda s: s.position)
        step_meta: dict[str, dict[str, Any]] = {}

        if task_nodes is not None:
            for node in task_nodes:
                task_key = node.to_task_spec().key
                matching_step = next(
                    (s for s in steps if s.name == task_key or s.id == node.task_id), None
                )
                step_id = matching_step.id if matching_step else node.task_id
                ownership = getattr(
                    node.target_files_ownership, "value", str(node.target_files_ownership)
                )
                step_meta[step_id] = {
                    "task_key": task_key,
                    "depends_on": list(node.dependencies),
                    "target_files": list(node.target_files),
                    "target_files_ownership": ownership,
                    "parallel_safe": bool(node.parallel_safe),
                }

        for step in steps:
            if step.id not in step_meta:
                payload = dict(step.input_payload or {})
                step_meta[step.id] = {
                    "task_key": payload.get("task_key", step.name),
                    "depends_on": list(payload.get("depends_on", [])),
                    "target_files": list(payload.get("target_files", [])),
                    "target_files_ownership": payload.get("target_files_ownership", "KNOWN"),
                    "parallel_safe": bool(payload.get("parallel_safe", False)),
                }

        pending_steps = {s.id: s for s in steps}
        running_tasks: dict[str, asyncio.Task[ExecutionContext]] = {}
        task_step_map: dict[asyncio.Task[ExecutionContext], WorkflowStep] = {}
        completed_keys: set[str] = set()
        failed_keys: set[str] = set()

        active_agents: set[str] = set()
        active_target_files: set[str] = set()
        active_unknown_count: int = 0
        failed_step_encountered = False

        task_timestamps: dict[str, dict[str, datetime]] = {}

        while pending_steps or running_tasks:
            scheduled_any = False
            for step_id, step in list(pending_steps.items()):
                meta = step_meta[step_id]
                deps = meta["depends_on"]

                deps_met = all(
                    dep in completed_keys
                    or any(s.id == dep for s in steps if s.id in completed_keys)
                    for dep in deps
                )
                if not deps_met:
                    dep_failed = any(
                        dep in failed_keys or any(s.id == dep for s in steps if s.id in failed_keys)
                        for dep in deps
                    )
                    if dep_failed:
                        pending_steps.pop(step_id, None)
                        failed_keys.add(meta["task_key"])
                        failed_keys.add(step_id)
                        with self._db_lock:
                            workflow_service.transition_step(self._db, step.id, StepStatus.FAILED)
                        failed_step_encountered = True
                    continue

                if len(running_tasks) >= max_concurrency:
                    break

                if step.agent_type in active_agents:
                    continue

                ownership = meta["target_files_ownership"]
                parallel_safe = meta["parallel_safe"]
                target_files = set(meta["target_files"])

                if (ownership != "KNOWN" or not parallel_safe or not target_files) and len(
                    running_tasks
                ) > 0:
                    continue

                if active_unknown_count > 0:
                    continue

                if target_files & active_target_files:
                    continue

                pending_steps.pop(step_id)
                active_agents.add(step.agent_type)
                active_target_files.update(target_files)
                if ownership != "KNOWN" or not parallel_safe or not target_files:
                    active_unknown_count += 1

                if workspace_watcher is not None and hasattr(
                    workspace_watcher, "register_active_task"
                ):
                    workspace_watcher.register_active_task(
                        step.id, step.agent_type, meta["target_files"]
                    )

                task_timestamps[step.id] = {"start": datetime.now(UTC)}

                task = asyncio.create_task(
                    asyncio.to_thread(self._execute_step, workflow, step, context)
                )
                running_tasks[step.id] = task
                task_step_map[task] = step
                scheduled_any = True

            if not running_tasks:
                if pending_steps and not scheduled_any:
                    for step_id, step in list(pending_steps.items()):
                        pending_steps.pop(step_id)
                        failed_keys.add(step.id)
                        with self._db_lock:
                            workflow_service.transition_step(self._db, step.id, StepStatus.FAILED)
                    failed_step_encountered = True
                break

            done, _ = await asyncio.wait(
                list(running_tasks.values()), return_when=asyncio.FIRST_COMPLETED
            )

            for finished_task in done:
                step = task_step_map.pop(finished_task)
                running_tasks.pop(step.id, None)
                meta = step_meta[step.id]

                active_agents.discard(step.agent_type)
                active_target_files.difference_update(meta["target_files"])
                if (
                    meta["target_files_ownership"] != "KNOWN"
                    or not meta["parallel_safe"]
                    or not meta["target_files"]
                ):
                    active_unknown_count = max(0, active_unknown_count - 1)

                if workspace_watcher is not None and hasattr(
                    workspace_watcher, "unregister_active_task"
                ):
                    workspace_watcher.unregister_active_task(step.id)

                task_timestamps[step.id]["end"] = datetime.now(UTC)

                try:
                    updated_context = finished_task.result()
                    context = updated_context
                    completed_keys.add(step.id)
                    completed_keys.add(meta["task_key"])
                except Exception as exc:
                    logger.warning("async_step_execution_failed step_id=%s exc=%s", step.id, exc)
                    failed_keys.add(step.id)
                    failed_keys.add(meta["task_key"])
                    failed_step_encountered = True

        if failed_step_encountered or len(completed_keys) < len(steps):
            final_wf = self._fail_workflow(
                workflow_id, error_message="one or more tasks in the workflow failed execution"
            )
        else:
            final_wf = self._succeed_workflow(workflow, steps, context)

        return final_wf, task_timestamps

    def resume_workflow(self, workflow_id: str) -> Workflow:
        """Resume a workflow left `RUNNING` by a process interruption.

        Raises `WorkflowNotFoundError` if the workflow does not exist,
        `InvalidWorkflowStateError` if it is not `RUNNING` (only a workflow a
        prior `execute_workflow` call left mid-flight is resumable — a
        `PENDING` workflow should use `execute_workflow` instead), and
        `WorkflowResumeConflictError` if another resume is already in
        progress for this workflow (detected via an atomic optimistic check
        on `Workflow.version`, so two concurrent resumes can never both
        proceed).

        Already-`SUCCEEDED` steps are never re-run: their persisted output
        seeds the execution context exactly as if they had just completed.
        A step still `RUNNING` at resume time (the one in-flight when the
        interruption happened) has its dangling attempt marked `FAILED` with
        a clear `EXECUTION_INTERRUPTED` reason — it cannot be assumed to
        have completed or to be safely retriable as-is — and is then
        re-attempted from a fresh attempt, exactly like any other retry.
        `step.attempt_count` (not a call-local counter) is what bounds total
        attempts to `max_attempts` across initial execution, retries, *and*
        any resume — an interrupted attempt already counts toward that total
        the moment it is marked `FAILED` above (see `_execute_step`).

        **Recovery semantics, stated plainly:**

        - This provides **at-least-once** execution for the interrupted
          step's external side effect, not exactly-once. If the underlying
          agent actually completed its work before the process crashed but
          the outcome was never persisted, resume cannot tell the
          difference from a genuine failure and will re-attempt — unless the
          provider itself has its own idempotency mechanism, nothing here
          prevents that side effect from running twice.
        - `app.engine.workflow.idempotency.IdempotentExecutionGuard` (the
          additive graph-scheduler layer's duplicate-execution guard) does
          **not** help here: it is process-local and in-memory, so it
          provides no protection at all across the kind of process
          restart/crash this method exists to recover from.
        - `WORKFLOW_RESUMED` is appended through the same tamper-evident,
          hash-linked audit chain as every other event — a resume is exactly
          as traceable and provenance-preserving as normal execution, not a
          special, less-audited path.
        - An interrupted attempt remains explicitly attributable after
          resume: its `StepAttempt` row is preserved (marked `FAILED` with
          `error_type="EXECUTION_INTERRUPTED"`, not deleted or overwritten),
          and the `WORKFLOW_RESUMED` event's payload lists exactly which
          step IDs were already succeeded, which were interrupted, and which
          are about to run.
        """
        workflow = workflow_service.get_workflow(self._db, workflow_id)
        if workflow is None:
            raise WorkflowNotFoundError(workflow_id)
        if WorkflowStatus(workflow.status) is not WorkflowStatus.RUNNING:
            raise InvalidWorkflowStateError(workflow_id, WorkflowStatus(workflow.status))

        claimed = workflow_service.claim_workflow_for_resume(
            self._db, workflow_id, expected_version=workflow.version
        )
        if not claimed:
            raise WorkflowResumeConflictError(workflow_id)
        workflow = self._reload(workflow_id)

        logger.info("workflow_resume_started workflow_id=%s", workflow_id)
        context = ExecutionContext(
            workflow_id=workflow.id, workflow_input=dict(workflow.input_payload)
        )
        all_steps = sorted(workflow.steps, key=lambda s: s.position)
        pending_steps: list[WorkflowStep] = []
        already_succeeded_step_ids: list[str] = []
        interrupted_step_ids: list[str] = []
        for step in all_steps:
            if StepStatus(step.status) is StepStatus.SUCCEEDED:
                context = context.with_step_output(step.id, step.output_payload or {})
                already_succeeded_step_ids.append(step.id)
                continue
            if StepStatus(step.status) is StepStatus.RUNNING:
                self._mark_interrupted_attempt_failed(step)
                workflow_service.transition_step(self._db, step.id, StepStatus.RETRYING)
                interrupted_step_ids.append(step.id)
            pending_steps.append(step)

        # Step IDs only — internal identifiers already exposed elsewhere in
        # the API, never sensitive payload content — so a future
        # explainability/observability consumer can trace exactly which
        # steps were already done, which were mid-flight when the process
        # was interrupted, and which are about to run, without having to
        # cross-reference separate per-step events to reconstruct it.
        audit_service.append_event(
            self._db,
            workflow_id=workflow.id,
            event_type=AuditEventType.WORKFLOW_RESUMED,
            actor_type=ActorType.SYSTEM,
            actor_id=_SYSTEM_ACTOR,
            payload={
                "resumed_step_count": len(pending_steps),
                "resumed_step_ids": [step.id for step in pending_steps],
                "already_succeeded_step_count": len(already_succeeded_step_ids),
                "already_succeeded_step_ids": already_succeeded_step_ids,
                "interrupted_step_ids": interrupted_step_ids,
            },
        )

        return self._run_to_completion(workflow, all_steps, pending_steps, context)

    def _mark_interrupted_attempt_failed(self, step: WorkflowStep) -> None:
        """Mark a step's dangling `RUNNING` attempt `FAILED` before resume re-attempts it.

        Never assumes the interrupted attempt actually failed on the
        provider side — only that this process can no longer observe its
        outcome, so it must not be trusted as a completed attempt.
        """
        if not step.attempts:
            return
        latest = max(step.attempts, key=lambda attempt: attempt.attempt_number)
        if AttemptStatus(latest.status) is not AttemptStatus.RUNNING:
            return
        workflow_service.complete_step_attempt(
            self._db,
            latest.id,
            status=AttemptStatus.FAILED,
            error_type="EXECUTION_INTERRUPTED",
            error_message="attempt was in-flight when the process was interrupted",
        )
        audit_service.append_event(
            self._db,
            workflow_id=step.workflow_id,
            step_id=step.id,
            execution_attempt_id=latest.id,
            event_type=AuditEventType.EXECUTION_ATTEMPT_FAILED,
            actor_type=ActorType.SYSTEM,
            actor_id=_SYSTEM_ACTOR,
            payload={"error_code": "EXECUTION_INTERRUPTED", "reason": "process_interrupted"},
        )

    def _run_to_completion(
        self,
        workflow: Workflow,
        all_steps: list[WorkflowStep],
        pending_steps: list[WorkflowStep],
        context: ExecutionContext,
    ) -> Workflow:
        """Run `pending_steps` in order, then succeed the workflow using `all_steps`
        for output aggregation (so a resumed run's final output includes
        already-succeeded steps too, identical to an uninterrupted run)."""
        for step in pending_steps:
            try:
                context = self._execute_step(workflow, step, context)
            except ExecutorNotRegisteredError as exc:
                self._fail_workflow(workflow.id, error_message=str(exc))
                logger.warning(
                    "workflow_execution_failed workflow_id=%s reason=%s", workflow.id, exc
                )
                self._maybe_auto_compensate(workflow.id)
                raise
            except CircuitBreakerOpenError as exc:
                self._fail_workflow(workflow.id, error_message=str(exc))
                logger.warning(
                    "workflow_execution_failed workflow_id=%s reason=%s", workflow.id, exc
                )
                self._maybe_auto_compensate(workflow.id)
                raise
            except StepExecutionError as exc:
                self._fail_workflow(workflow.id, error_message=str(exc))
                logger.warning(
                    "workflow_execution_failed workflow_id=%s reason=%s", workflow.id, exc
                )
                self._maybe_auto_compensate(workflow.id)
                return self._reload(workflow.id)
            except Exception:
                self._fail_workflow(
                    workflow.id, error_message="an unexpected error occurred during step execution"
                )
                logger.exception(
                    "workflow_execution_failed workflow_id=%s unexpected_error=true", workflow.id
                )
                raise

        return self._succeed_workflow(workflow, all_steps, context)

    def _execute_step(
        self, workflow: Workflow, step: WorkflowStep, context: ExecutionContext
    ) -> ExecutionContext:
        try:
            bind = self._db.get_bind()
            factory = sessionmaker(bind=bind, autoflush=False, expire_on_commit=False)
            worker_db = factory()
        except Exception as exc:
            logger.exception(
                "worker_session_creation_failed workflow_id=%s step_id=%s", workflow.id, step.id
            )
            raise RuntimeError(
                f"Failed to create independent database session for worker step '{step.id}': {exc}"
            ) from exc

        try:
            return self._execute_step_with_db(worker_db, workflow, step, context)
        finally:
            worker_db.close()

    def _execute_step_with_db(
        self, db: Session, workflow: Workflow, step: WorkflowStep, context: ExecutionContext
    ) -> ExecutionContext:
        workflow_service.transition_step(db, step.id, StepStatus.RUNNING)
        audit_service.append_event(
            db,
            workflow_id=workflow.id,
            step_id=step.id,
            event_type=AuditEventType.STEP_EXECUTION_STARTED,
            actor_type=ActorType.SYSTEM,
            actor_id=_SYSTEM_ACTOR,
            payload={"agent_type": step.agent_type, "position": step.position},
        )
        try:
            executor = self._registry.get(step.agent_type)
        except ExecutorNotRegisteredError as exc:
            attempt = workflow_service.create_step_attempt(db, step.id)
            logger.warning(
                "executor_not_registered workflow_id=%s step_id=%s agent_type=%s",
                workflow.id,
                step.id,
                step.agent_type,
            )
            self._fail_step(
                attempt,
                step,
                error_type="AGENT_EXECUTOR_NOT_REGISTERED",
                error_message=str(exc),
                db=db,
            )
            audit_service.append_event(
                db,
                workflow_id=workflow.id,
                step_id=step.id,
                execution_attempt_id=attempt.id,
                event_type=AuditEventType.STEP_FAILED,
                actor_type=ActorType.SYSTEM,
                actor_id=_SYSTEM_ACTOR,
                payload={"error_code": "AGENT_EXECUTOR_NOT_REGISTERED"},
            )
            raise

        breaker = self._circuit_breakers.get_or_create(step.agent_type)
        max_attempts = step.max_attempts
        attempt_number = step.attempt_count
        if attempt_number >= max_attempts:
            logger.warning(
                "step_attempt_budget_already_exhausted workflow_id=%s step_id=%s "
                "attempt_count=%s max_attempts=%s",
                workflow.id,
                step.id,
                attempt_number,
                max_attempts,
            )
            workflow_service.transition_step(db, step.id, StepStatus.FAILED)
            audit_service.append_event(
                db,
                workflow_id=workflow.id,
                step_id=step.id,
                event_type=AuditEventType.STEP_FAILED,
                actor_type=ActorType.SYSTEM,
                actor_id=_SYSTEM_ACTOR,
                payload={
                    "error_code": "MAX_ATTEMPTS_EXHAUSTED",
                    "attempt_count": attempt_number,
                    "max_attempts": max_attempts,
                },
            )
            raise StepExecutionError(
                f"step '{step.id}' already exhausted its {max_attempts} allowed "
                "attempt(s) before this execution began",
                error_type="MAX_ATTEMPTS_EXHAUSTED",
            )

        while True:
            attempt_number += 1
            attempt = workflow_service.create_step_attempt(db, step.id)
            logger.info(
                "step_execution_started workflow_id=%s step_id=%s agent_type=%s "
                "attempt_number=%s max_attempts=%s",
                workflow.id,
                step.id,
                step.agent_type,
                attempt_number,
                max_attempts,
            )
            audit_service.append_event(
                db,
                workflow_id=workflow.id,
                step_id=step.id,
                execution_attempt_id=attempt.id,
                event_type=AuditEventType.EXECUTION_ATTEMPT_STARTED,
                actor_type=ActorType.SYSTEM,
                actor_id=_SYSTEM_ACTOR,
                payload={"attempt_number": attempt_number, "max_attempts": max_attempts},
            )

            try:
                breaker.before_call()
            except CircuitBreakerOpenError as exc:
                self._fail_step(
                    attempt,
                    step,
                    error_type="CIRCUIT_BREAKER_OPEN",
                    error_message=str(exc),
                    db=db,
                )
                audit_service.append_event(
                    db,
                    workflow_id=workflow.id,
                    step_id=step.id,
                    execution_attempt_id=attempt.id,
                    event_type=AuditEventType.CIRCUIT_BREAKER_REJECTED,
                    actor_type=ActorType.SYSTEM,
                    actor_id=_SYSTEM_ACTOR,
                    payload={"agent_type": step.agent_type, "circuit_state": "open"},
                )
                raise

            try:
                request = StepExecutionRequest(
                    workflow_id=workflow.id,
                    step_id=step.id,
                    step_name=step.name,
                    agent_type=step.agent_type,
                    step_input=dict(step.input_payload),
                    workflow_input=context.workflow_input,
                    previous_step_outputs=context.previous_step_outputs,
                    workspace_root=self._workspace_root,
                )
                output = _ensure_json_compatible(executor.execute(request))
            except StepExecutionError as exc:
                if exc.retryable:
                    breaker.record_failure()
                circuit_open_now = breaker.snapshot().state is CircuitState.OPEN
                can_retry = exc.retryable and attempt_number < max_attempts and not circuit_open_now
                logger.warning(
                    "step_execution_failed workflow_id=%s step_id=%s error_type=%s "
                    "retryable=%s attempt_number=%s",
                    workflow.id,
                    step.id,
                    exc.error_type,
                    exc.retryable,
                    attempt_number,
                )
                if can_retry:
                    workflow_service.complete_step_attempt(
                        db,
                        attempt.id,
                        status=AttemptStatus.FAILED,
                        error_type=exc.error_type,
                        error_message=str(exc),
                    )
                    retry_exec_status, retry_failure_category = _classify_failed_attempt(
                        exc.error_type
                    )
                    self._record_step_learning_event(
                        step,
                        attempt,
                        execution_status=retry_exec_status,
                        failure_category=retry_failure_category,
                        is_terminal=False,
                        db=db,
                    )
                    audit_service.append_event(
                        db,
                        workflow_id=workflow.id,
                        step_id=step.id,
                        execution_attempt_id=attempt.id,
                        event_type=AuditEventType.EXECUTION_ATTEMPT_FAILED,
                        actor_type=ActorType.SYSTEM,
                        actor_id=_SYSTEM_ACTOR,
                        payload={"error_code": exc.error_type, "attempt_number": attempt_number},
                    )
                    workflow_service.transition_step(db, step.id, StepStatus.RETRYING)
                    delay = self._retry_policy.compute_delay(attempt_number)
                    logger.info(
                        "agent_retry_scheduled workflow_id=%s step_id=%s attempt_number=%s "
                        "delay_seconds=%.3f",
                        workflow.id,
                        step.id,
                        attempt_number,
                        delay,
                    )
                    audit_service.append_event(
                        db,
                        workflow_id=workflow.id,
                        step_id=step.id,
                        execution_attempt_id=attempt.id,
                        event_type=AuditEventType.STEP_RETRY_SCHEDULED,
                        actor_type=ActorType.SYSTEM,
                        actor_id=_SYSTEM_ACTOR,
                        payload={"attempt_number": attempt_number, "delay_seconds": delay},
                    )
                    self._sleeper.sleep(delay)
                    workflow_service.transition_step(db, step.id, StepStatus.RUNNING)
                    continue
                self._fail_step(
                    attempt, step, error_type=exc.error_type, error_message=str(exc), db=db
                )
                audit_service.append_event(
                    db,
                    workflow_id=workflow.id,
                    step_id=step.id,
                    execution_attempt_id=attempt.id,
                    event_type=AuditEventType.EXECUTION_ATTEMPT_FAILED,
                    actor_type=ActorType.SYSTEM,
                    actor_id=_SYSTEM_ACTOR,
                    payload={"error_code": exc.error_type, "attempt_number": attempt_number},
                )
                audit_service.append_event(
                    db,
                    workflow_id=workflow.id,
                    step_id=step.id,
                    execution_attempt_id=attempt.id,
                    event_type=AuditEventType.STEP_FAILED,
                    actor_type=ActorType.SYSTEM,
                    actor_id=_SYSTEM_ACTOR,
                    payload={"error_code": exc.error_type},
                )
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
                    db=db,
                )
                audit_service.append_event(
                    db,
                    workflow_id=workflow.id,
                    step_id=step.id,
                    execution_attempt_id=attempt.id,
                    event_type=AuditEventType.STEP_FAILED,
                    actor_type=ActorType.SYSTEM,
                    actor_id=_SYSTEM_ACTOR,
                    payload={"error_code": "UNEXPECTED_ERROR"},
                )
                raise

            breaker.record_success()
            workflow_service.complete_step_attempt(
                db, attempt.id, status=AttemptStatus.SUCCEEDED, output_payload=output
            )
            self._record_step_learning_event(
                step,
                attempt,
                execution_status=AgentExecutionStatus.SUCCEEDED,
                is_terminal=True,
                db=db,
            )
            audit_service.append_event(
                db,
                workflow_id=workflow.id,
                step_id=step.id,
                execution_attempt_id=attempt.id,
                event_type=AuditEventType.EXECUTION_ATTEMPT_SUCCEEDED,
                actor_type=ActorType.AGENT,
                actor_id=step.agent_type,
                payload={"attempt_number": attempt_number, "output_digest": compute_digest(output)},
            )
            updated_step = workflow_service.transition_step(db, step.id, StepStatus.SUCCEEDED)
            updated_step.output_payload = output
            audit_service.append_event(
                db,
                workflow_id=workflow.id,
                step_id=step.id,
                execution_attempt_id=attempt.id,
                event_type=AuditEventType.STEP_SUCCEEDED,
                actor_type=ActorType.AGENT,
                actor_id=step.agent_type,
                payload={"position": step.position, "output_digest": compute_digest(output)},
            )

            logger.info(
                "step_execution_succeeded workflow_id=%s step_id=%s attempt_number=%s",
                workflow.id,
                step.id,
                attempt_number,
            )
            return context.with_step_output(step.id, output)

    def _fail_step(
        self,
        attempt: StepAttempt,
        step: WorkflowStep,
        *,
        error_type: str,
        error_message: str,
        db: Session | None = None,
    ) -> None:
        use_db = db or self._db
        workflow_service.complete_step_attempt(
            use_db,
            attempt.id,
            status=AttemptStatus.FAILED,
            error_type=error_type,
            error_message=error_message,
        )
        exec_status, failure_category = _classify_failed_attempt(error_type)
        self._record_step_learning_event(
            step,
            attempt,
            execution_status=exec_status,
            failure_category=failure_category,
            is_terminal=True,
            db=use_db,
        )
        workflow_service.transition_step(use_db, step.id, StepStatus.FAILED)

    def _fail_workflow(self, workflow_id: str, *, error_message: str) -> Workflow:
        with self._db_lock:
            workflow_service.transition_workflow(self._db, workflow_id, WorkflowStatus.FAILED)
            workflow = workflow_service.set_workflow_result(
                self._db, workflow_id, error_message=error_message
            )
            audit_service.append_event(
                self._db,
                workflow_id=workflow_id,
                event_type=AuditEventType.WORKFLOW_FAILED,
                actor_type=ActorType.SYSTEM,
                actor_id=_SYSTEM_ACTOR,
                payload={"error_message": error_message},
            )
            return workflow

    def _succeed_workflow(
        self, workflow: Workflow, steps: list[WorkflowStep], context: ExecutionContext
    ) -> Workflow:
        with self._db_lock:
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
            audit_service.append_event(
                self._db,
                workflow_id=workflow.id,
                event_type=AuditEventType.WORKFLOW_SUCCEEDED,
                actor_type=ActorType.SYSTEM,
                actor_id=_SYSTEM_ACTOR,
                payload={"step_count": len(steps)},
            )
            logger.info("workflow_execution_succeeded workflow_id=%s", workflow.id)
            return self._reload(workflow.id)

    def _maybe_auto_compensate(self, workflow_id: str) -> None:
        if not self._auto_compensate_on_failure or self._compensation_service is None:
            return
        try:
            with self._db_lock:
                self._compensation_service.compensate_workflow(workflow_id)
        except Exception:
            logger.exception("automatic_compensation_failed workflow_id=%s", workflow_id)

    def _reload(self, workflow_id: str) -> Workflow:
        with self._db_lock:
            workflow = workflow_service.get_workflow(self._db, workflow_id)
            if workflow is None:
                raise RuntimeError(f"workflow '{workflow_id}' disappeared during execution")
            return workflow
