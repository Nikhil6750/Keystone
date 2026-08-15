"""`EndToEndOrchestrationService`: the Stage 8C.1 application-service layer
composing every already-certified Keystone subsystem into one pipeline.

```
Goal (OrchestrationRequest)
  -> Phase A: Knowledge (Stage 6A search [+ Stage 7.5 adaptive reranking] -> ContextBuilder)
  -> Phase B: Manager / Planning (ManagerOrchestrator -> Planner, unmodified)
  -> Phase C: Routing (build_routing_request -> Router, unmodified)
  -> Phase D: Workflow compile + execute (compiler.py -> workflow_service -> WorkflowEngine)
  -> Phase E: Verification + recovery (verify_one/aggregate -> decide_recovery/reroute, unmodified)
  -> Phase F: Learning (WorkflowEngine's own learning_persistence wiring, unmodified)
  -> Phase G: Retrieval feedback (RetrievalFeedback, only after verification PASSED)
  -> OrchestrationResult
```

**This module owns none of the logic in that diagram** -- every phase
calls an existing, certified component unmodified. What this module adds
is exactly the glue architecture discovery confirmed did not exist yet:
`runtime.py` (live `CandidateAgent` assembly), `compiler.py`
(`WorkflowPlan` -> `WorkflowCreate`), `verification_adapter.py`
(`StepAttempt` -> `ObservedOutcome`), and `knowledge_adapter.py` (the two
`KnowledgeSearchResult` types' conversion). See each module's docstring
for exactly what gap it closes and why.

**Authority boundaries preserved, explicitly:**

- The Manager can only ever influence `RoutingConstraints.preferred_agent_types`
  (Stage 8A's own `ManagerOrchestrator`, unmodified) -- never eligibility.
- `Router.route()` (unmodified) is the only place `selected_agent_type` is
  decided; a `None` selection for any task halts the whole request before
  any `Workflow` is created (`OrchestrationOutcome.NO_ELIGIBLE_ROUTE`).
- `WorkflowEngine` (unmodified) owns all workflow/step/attempt state
  transitions, retries, and circuit-breaker behavior.
- Verification status comes only from `verify_one`/`aggregate`
  (unmodified, Stage 4E) via `WorkflowEngine`'s own `VerificationResolver`
  seam -- this service never marks anything verified itself, and
  `execution_status`/`verification_status` are never conflated (a
  `SUCCEEDED` execution with a non-PASSED verification is recorded and
  reported as exactly that, never silently upgraded).
- Recovery decisions come only from `decide_recovery`/`reroute`
  (unmodified, Stage 4E), bounded by `RecoveryPolicy.max_attempts` --
  there is no separate, unbounded correction loop here.
- Learning events are written only through `LearningPersistenceService`
  (unmodified, Stage 5), wired into `WorkflowEngine` itself so a step's
  execution and verification outcome are recorded together, once, by the
  same component that already owns that write path.
- Retrieval feedback (`RetrievalFeedback`, Stage 7.5, unmodified) is only
  ever constructed with `verification_status=VerificationStatus.PASSED`
  as positive evidence -- never merely because a chunk was retrieved or
  used.

**Stage 8C.2 event instrumentation, purely observational.** `orchestrate()`
optionally emits `OrchestrationEvent`s (`app.engine.orchestration.events`)
at meaningful phase boundaries, to an injected `OrchestrationEventSink`
(default: `NullEventSink`, a no-op -- every existing caller that never
passes `event_sink=` observes zero behavior change). Every phase method
below is completely unchanged by this: emission happens only in
`orchestrate()` itself, after a phase's synchronous call already returned,
using data that phase already computed -- never inside a phase method,
never influencing what any phase decides. A sink failure is caught and
logged, never re-raised (see `_emit`): instrumentation must never turn a
verified success into a business failure.

**Recovery scope, documented.** Recovery re-executes only the specific
steps whose verification did not pass, as an independent recovery
`Workflow` (their `TaskSpec.input_payload` is static -- the current
Planner never populates it from another task's runtime output -- so
re-running just the failed subset, with `depends_on` cleared for that
recovery-only compilation, is correct, not merely convenient; see
`_run_recovery_cycle`). This is a deliberate Stage 8C.1 scope boundary,
not a redesign of Stage 4E's recovery semantics themselves.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.contracts.knowledge import KnowledgeSearchResult as ContractKnowledgeSearchResult
from app.contracts.planning import PlanningRequest, TaskSpec, WorkflowPlan
from app.contracts.quality import QualityExecutionContext, QualityRun
from app.contracts.routing import RoutingRequest
from app.contracts.verification import VerificationResult, VerificationStatus
from app.engine.adaptive_retrieval.feedback import RetrievalFeedback, RetrievalFeedbackRepository
from app.engine.adaptive_retrieval.models import RetrievalObservation
from app.engine.adaptive_retrieval.passport import RetrievalPassport
from app.engine.adaptive_retrieval.policy import AdaptiveRetrievalPolicy
from app.engine.adaptive_retrieval.reranking import AdaptiveRetriever, results_only
from app.engine.benchmark_learning.models import EvidenceSource
from app.engine.context import ExecutionContext
from app.engine.knowledge.context import ContextBudget, ContextBuilder
from app.engine.knowledge.index import KnowledgeIndex
from app.engine.knowledge.retrieval import KnowledgeSearchRequest, search
from app.engine.manager.context import build_manager_request
from app.engine.manager.orchestrator import (
    ManagerOrchestrationPolicy,
    ManagerOrchestrationResult,
    ManagerOrchestrator,
)
from app.engine.manager.protocol import ManagerModel
from app.engine.manager.validation import ManagerProposalValidator
from app.engine.orchestration.compiler import compile_workflow_create, topological_order
from app.engine.orchestration.errors import (
    OrchestrationPersistenceError,
)
from app.engine.orchestration.events import (
    NullEventSink,
    OrchestrationEvent,
    OrchestrationEventSequence,
    OrchestrationEventSink,
    OrchestrationEventType,
)
from app.engine.orchestration.evidence_collector import WorkspaceEvidenceCollector
from app.engine.orchestration.knowledge_adapter import (
    build_manager_knowledge_context,
    build_retrieval_observation,
)
from app.engine.orchestration.models import (
    OrchestrationOutcome,
    OrchestrationRequest,
    OrchestrationResult,
)
from app.engine.orchestration.runtime import RuntimeCandidateProvider
from app.engine.orchestration.verification_adapter import build_observed_outcome
from app.engine.planning.planner import Planner
from app.engine.quality.coordinator import QualityFactoryCoordinator
from app.engine.quality.repair import QualityRepairManager
from app.engine.registry import ExecutorRegistry
from app.engine.routing.availability import CandidateAgent
from app.engine.routing.request_builder import build_routing_request
from app.engine.routing.router import Router
from app.engine.skills.adaptive_rag import SkillAdaptiveRAGTracker
from app.engine.skills.agent_intelligence import SkillAgentIntelligenceEngine
from app.engine.skills.evidence import SkillEvidenceRepository, SqlAlchemySkillEvidenceRepository
from app.engine.skills.prompt_integration import attach_skill_to_task_payload
from app.engine.skills.registry import SkillRegistry
from app.engine.skills.retriever import SkillRetriever
from app.engine.verification.aggregation import AggregatedVerification, CheckOutcome, aggregate
from app.engine.verification.recovery import (
    RecoveryAction,
    RecoveryDecision,
    RecoveryPolicy,
    decide_recovery,
    reroute,
)
from app.engine.verification.verifier import verify_one
from app.engine.workflow_engine import WorkflowEngine
from app.models.enums import AttemptStatus, WorkflowStatus
from app.models.step_attempt import StepAttempt
from app.models.workflow import Workflow
from app.models.workflow_step import WorkflowStep
from app.persistence.service import LearningPersistenceService, build_event_id
from app.resilience.circuit_breaker import CircuitBreakerOpenError, CircuitBreakerRegistry
from app.resilience.retry import RetryPolicy
from app.resilience.sleeper import RealSleeper, Sleeper
from app.services import workflow_service

logger = logging.getLogger(__name__)

_DEFAULT_CIRCUIT_FAILURE_THRESHOLD = 3
_DEFAULT_CIRCUIT_RECOVERY_TIMEOUT_SECONDS = 30.0
_DEFAULT_RETRY_BASE_DELAY_SECONDS = 0.5
_DEFAULT_RETRY_MAX_DELAY_SECONDS = 5.0
_DEFAULT_KNOWLEDGE_SEARCH_LIMIT = 10


@dataclass(frozen=True)
class _RoutingContext:
    """What a recovery cycle needs to re-route one task: its original
    `RoutingRequest` (so `reroute()` can preserve every other constraint)
    and the candidate pool as it existed at initial-routing time."""

    request: RoutingRequest
    candidates: list[CandidateAgent]


class EndToEndOrchestrationService:
    """Composes Knowledge, Manager, Planner, Router, Workflow, Verification,
    Recovery, Learning, and Retrieval feedback into one pipeline. See
    module docstring for the exact phase order and authority boundaries.
    """

    def __init__(
        self,
        *,
        db: Session,
        registry: ExecutorRegistry,
        candidate_provider: RuntimeCandidateProvider,
        manager_model: ManagerModel | None = None,
        knowledge_index: KnowledgeIndex | None = None,
        adaptive_retriever: AdaptiveRetriever | None = None,
        production_retrieval_passports: dict[str, RetrievalPassport] | None = None,
        retrieval_feedback_repository: RetrievalFeedbackRepository | None = None,
        planner: Planner | None = None,
        router: Router | None = None,
        manager_orchestrator: ManagerOrchestrator | None = None,
        manager_validator: ManagerProposalValidator | None = None,
        manager_policy: ManagerOrchestrationPolicy | None = None,
        recovery_policy: RecoveryPolicy | None = None,
        circuit_breakers: CircuitBreakerRegistry | None = None,
        retry_policy: RetryPolicy | None = None,
        sleeper: Sleeper | None = None,
        learning_persistence: LearningPersistenceService | None = None,
        context_budget: ContextBudget | None = None,
        knowledge_search_limit: int = _DEFAULT_KNOWLEDGE_SEARCH_LIMIT,
        event_sink: OrchestrationEventSink | None = None,
        event_sequence: OrchestrationEventSequence | None = None,
        skill_registry: SkillRegistry | None = None,
        skill_evidence_repo: SkillEvidenceRepository | None = None,
        skill_retriever: SkillRetriever | None = None,
        skill_adaptive_tracker: SkillAdaptiveRAGTracker | None = None,
        skill_agent_intelligence: SkillAgentIntelligenceEngine | None = None,
        quality_coordinator: QualityFactoryCoordinator | None = None,
    ) -> None:
        self._db = db
        self._registry = registry
        self._workspace_root: str | None = None
        self._last_quality_run: QualityRun | None = None
        self._candidate_provider = candidate_provider
        self._knowledge_index = knowledge_index
        self._adaptive_retriever = adaptive_retriever
        self._production_retrieval_passports = production_retrieval_passports or {}
        self._retrieval_feedback_repository = retrieval_feedback_repository
        self._planner = planner or Planner()
        self._router = router or Router()
        self._manager_validator = manager_validator or ManagerProposalValidator()
        self._manager_orchestrator = manager_orchestrator or ManagerOrchestrator(
            manager_model=manager_model,
            planner=self._planner,
            validator=self._manager_validator,
            policy=manager_policy,
        )
        self._recovery_policy = recovery_policy or RecoveryPolicy()
        self._circuit_breakers = circuit_breakers or CircuitBreakerRegistry(
            failure_threshold=_DEFAULT_CIRCUIT_FAILURE_THRESHOLD,
            recovery_timeout_seconds=_DEFAULT_CIRCUIT_RECOVERY_TIMEOUT_SECONDS,
        )
        self._retry_policy = retry_policy or RetryPolicy(
            base_delay_seconds=_DEFAULT_RETRY_BASE_DELAY_SECONDS,
            max_delay_seconds=_DEFAULT_RETRY_MAX_DELAY_SECONDS,
        )
        self._sleeper = sleeper or RealSleeper()
        self._learning_persistence = learning_persistence or LearningPersistenceService()
        self._context_budget = context_budget or ContextBudget()
        self._knowledge_search_limit = knowledge_search_limit
        self._event_sink = event_sink or NullEventSink()
        self._event_sequence = event_sequence or OrchestrationEventSequence()

        # Skill Foundry Wiring (P1-1, P1-2, P1-4, P1-6)
        self._skill_evidence_repo = skill_evidence_repo or SqlAlchemySkillEvidenceRepository(
            session_factory=lambda: self._db
        )
        self._skill_registry = skill_registry or SkillRegistry(
            evidence_repo=self._skill_evidence_repo,
            session_factory=lambda: self._db,
        )
        self._skill_adaptive_tracker = skill_adaptive_tracker or SkillAdaptiveRAGTracker()
        self._skill_retriever = skill_retriever or SkillRetriever(
            registry=self._skill_registry,
            evidence_repo=self._skill_evidence_repo,
            adaptive_tracker=self._skill_adaptive_tracker,
        )
        self._skill_agent_intelligence = skill_agent_intelligence or SkillAgentIntelligenceEngine(
            evidence_repo=self._skill_evidence_repo
        )

        # Stage 9D Software Quality Factory Wiring
        self._quality_coordinator = quality_coordinator
        self._quality_runs_by_task_key: dict[str, QualityRun] = {}

    # --- Stage 8C.2: observational event emission ---------------------------

    async def _emit(
        self, execution_id: str, event_type: OrchestrationEventType, **fields: object
    ) -> None:
        """Build and emit one `OrchestrationEvent`, best-effort. Unlike
        `StateSink` (deliberately fail-fast for its own, different, load-
        bearing consumer), a broken/slow `OrchestrationEventSink` here is
        caught and logged, never re-raised -- see module docstring. Never
        called from inside a phase method; only from `orchestrate()`,
        after the phase it describes already ran and decided everything
        for itself."""
        sequence = self._event_sequence.next()
        event = OrchestrationEvent(
            event_id=f"evt-{execution_id}-{sequence:04d}",
            execution_id=execution_id,
            sequence=sequence,
            event_type=event_type,
            timestamp=datetime.now(UTC),
            **fields,  # type: ignore[arg-type]
        )
        try:
            await self._event_sink.on_event(event)
        except Exception:
            logger.exception(
                "orchestration_event_sink_failed event_type=%s execution_id=%s",
                event_type.value,
                execution_id,
            )

    # --- Public entry point -------------------------------------------------

    async def orchestrate(self, request: OrchestrationRequest) -> OrchestrationResult:
        """The single public entry point. `async` because Phase B's
        `ManagerOrchestrator.orchestrate()` (Stage 8A, unmodified) is
        itself `async` -- every other phase is synchronous DB/CPU work,
        called directly (not offloaded), matching how `WorkflowEngine`
        itself is synchronous throughout this codebase today."""
        execution_id = request.request_id
        # Already validated by `OrchestrationRequest`'s own field validator
        # (absolute, exists, is a directory) -- read once here and handed
        # to every `WorkflowEngine` this orchestration constructs (Phase D
        # and any recovery cycle), never re-derived from `goal` or any
        # other free-text field.
        self._workspace_root = request.workspace_root
        warnings: list[str] = []
        issue_codes: list[str] = []

        await self._emit(execution_id, OrchestrationEventType.EXECUTION_STARTED)

        await self._emit(execution_id, OrchestrationEventType.KNOWLEDGE_STARTED)
        manager_knowledge_context, knowledge_result_count, adaptive_used, observation = (
            self._phase_a_knowledge(request)
        )
        await self._emit(
            execution_id,
            OrchestrationEventType.KNOWLEDGE_COMPLETED,
            message=f"knowledge_result_count={knowledge_result_count}",
        )

        await self._emit(execution_id, OrchestrationEventType.MANAGER_STARTED)
        manager_outcome = await self._phase_b_manager(request, manager_knowledge_context)
        plan = manager_outcome.plan
        warnings.extend(manager_outcome.warnings)
        issue_codes.extend(manager_outcome.validation_issue_codes)
        await self._emit(
            execution_id,
            OrchestrationEventType.MANAGER_COMPLETED,
            status=str(manager_outcome.manager_used),
        )
        if manager_outcome.fallback_used:
            await self._emit(execution_id, OrchestrationEventType.MANAGER_FALLBACK)

        if not plan.tasks:
            result = self._result(
                request,
                outcome=OrchestrationOutcome.RUNTIME_FAILURE,
                workflow_id=None,
                final_workflow_state=None,
                plan=plan,
                manager_outcome=manager_outcome,
                knowledge_result_count=knowledge_result_count,
                adaptive_used=adaptive_used,
                warnings=[*warnings, "planner produced an empty task list"],
                issue_codes=issue_codes,
            )
            await self._emit_execution_completed(execution_id, result)
            return result

        await self._emit(
            execution_id,
            OrchestrationEventType.PLANNING_COMPLETED,
            message=f"task_count={len(plan.tasks)}",
        )

        # Skill retrieval & enrichment for compiled task nodes (WHAT = Task, HOW = Skill)
        self._enrich_plan_with_skills(plan, request, execution_id)

        await self._emit(execution_id, OrchestrationEventType.ROUTING_STARTED)
        routing = self._phase_c_routing(request, plan)
        if routing is None:
            await self._emit(execution_id, OrchestrationEventType.ROUTING_FAILED)
            result = self._result(
                request,
                outcome=OrchestrationOutcome.NO_ELIGIBLE_ROUTE,
                workflow_id=None,
                final_workflow_state=None,
                plan=plan,
                manager_outcome=manager_outcome,
                knowledge_result_count=knowledge_result_count,
                adaptive_used=adaptive_used,
                warnings=warnings,
                issue_codes=issue_codes,
            )
            await self._emit_execution_completed(execution_id, result)
            return result
        agent_type_by_task_key, routing_context_by_task_key = routing
        selected_agent_types = tuple(sorted(set(agent_type_by_task_key.values())))
        for task_key, agent_type in agent_type_by_task_key.items():
            await self._emit(
                execution_id,
                OrchestrationEventType.ROUTING_TASK_SELECTED,
                task_key=task_key,
                agent_id=agent_type,
            )
            await self._emit(
                execution_id,
                OrchestrationEventType.AGENT_SELECTED,
                task_key=task_key,
                agent_id=agent_type,
            )

        try:
            workflow, step_to_task, results, learning_event_ids = await self._phase_d_execute(
                plan, agent_type_by_task_key, execution_id
            )
        except SQLAlchemyError as exc:
            raise OrchestrationPersistenceError(
                "workflow creation/execution failed at the persistence layer"
            ) from exc

        if workflow.status == WorkflowStatus.FAILED and not results:
            result = self._result(
                request,
                outcome=OrchestrationOutcome.RUNTIME_FAILURE,
                workflow_id=workflow.id,
                final_workflow_state=workflow.status,
                plan=plan,
                manager_outcome=manager_outcome,
                knowledge_result_count=knowledge_result_count,
                adaptive_used=adaptive_used,
                warnings=warnings,
                issue_codes=issue_codes,
                selected_agent_types=selected_agent_types,
                attempt_count=self._count_attempts(workflow),
                learning_event_ids=learning_event_ids,
            )
            await self._emit_execution_completed(execution_id, result)
            return result

        await self._emit(execution_id, OrchestrationEventType.VERIFICATION_STARTED)
        (
            final_workflow,
            aggregated,
            recovery_used,
            recovery_action,
            all_learning_event_ids,
            rerouted_tasks,
        ) = await asyncio.to_thread(
            self._phase_e_verify_and_recover,
            plan,
            workflow,
            step_to_task,
            results,
            agent_type_by_task_key,
            routing_context_by_task_key,
            learning_event_ids,
            execution_id,
        )
        await self._emit(
            execution_id,
            OrchestrationEventType.VERIFICATION_COMPLETED,
            verification_status=(
                aggregated.overall_status.value if aggregated is not None else None
            ),
        )
        if recovery_used:
            if rerouted_tasks:
                for r_task_key, r_prev, r_new, r_reason in rerouted_tasks:
                    await self._emit(
                        execution_id,
                        OrchestrationEventType.RECOVERY_STARTED,
                        task_key=r_task_key,
                        previous_agent_id=r_prev,
                        new_agent_id=r_new,
                        reason_category=r_reason,
                        status="rerouted",
                    )
            else:
                await self._emit(execution_id, OrchestrationEventType.RECOVERY_STARTED)

            if recovery_action == RecoveryAction.FAIL:
                await self._emit(execution_id, OrchestrationEventType.RECOVERY_EXHAUSTED)
            else:
                await self._emit(execution_id, OrchestrationEventType.RECOVERY_COMPLETED)

        retrieval_feedback_recorded = self._phase_g_feedback(
            observation, aggregated, final_workflow.id, request
        )
        self._record_skill_feedback(final_workflow, step_to_task, results, aggregated, execution_id)
        await self._emit(
            execution_id,
            OrchestrationEventType.RETRIEVAL_FEEDBACK_COMPLETED,
            status="recorded" if retrieval_feedback_recorded else "not_recorded",
        )

        outcome = self._determine_outcome(aggregated, recovery_action)
        attempt_count = self._count_attempts(final_workflow)

        result = self._result(
            request,
            outcome=outcome,
            workflow_id=final_workflow.id,
            final_workflow_state=final_workflow.status,
            plan=plan,
            manager_outcome=manager_outcome,
            knowledge_result_count=knowledge_result_count,
            adaptive_used=adaptive_used,
            warnings=warnings,
            issue_codes=issue_codes,
            selected_agent_types=selected_agent_types,
            attempt_count=attempt_count,
            verification_status=aggregated.overall_status if aggregated is not None else None,
            recovery_used=recovery_used,
            recovery_action=recovery_action,
            learning_event_ids=all_learning_event_ids,
            retrieval_feedback_recorded=retrieval_feedback_recorded,
        )
        await self._emit_execution_completed(execution_id, result)
        return result

    async def _emit_execution_completed(
        self, execution_id: str, result: OrchestrationResult
    ) -> None:
        """Always `execution.completed` -- the async job pipeline itself
        finished running without an unhandled exception, regardless of
        `result.outcome` (a normal, expected result value, never conflated
        with job/transport status; see `app.engine.orchestration.execution`
        for the distinct job-status concept the API layer tracks)."""
        await self._emit(
            execution_id,
            OrchestrationEventType.EXECUTION_COMPLETED,
            status=result.outcome.value,
            workflow_id=result.workflow_id,
            safe_issue_codes=result.issue_codes,
        )

    async def _emit_step_events(
        self, execution_id: str, workflow: Workflow, step_to_task: dict[str, TaskSpec]
    ) -> None:
        """Replays one `step.started` + one terminal `step.completed`/
        `step.failed` per step, from each step's final attempt --
        `WorkflowEngine.execute_workflow()` (Stage 2/3, unmodified) already
        ran every step synchronously by the time this is called, so this is
        an observational replay of what already happened, never a second
        execution or a new decision."""
        for step in sorted(workflow.steps, key=lambda s: s.position):
            if not step.attempts:
                continue
            attempt = max(step.attempts, key=lambda a: a.attempt_number)
            task = step_to_task.get(step.id)
            await self._emit(
                execution_id,
                OrchestrationEventType.STEP_STARTED,
                workflow_id=workflow.id,
                task_key=task.key if task is not None else None,
                agent_id=step.agent_type,
                attempt_number=attempt.attempt_number,
            )
            completed_type = (
                OrchestrationEventType.STEP_COMPLETED
                if attempt.status == AttemptStatus.SUCCEEDED
                else OrchestrationEventType.STEP_FAILED
            )
            await self._emit(
                execution_id,
                completed_type,
                workflow_id=workflow.id,
                task_key=task.key if task is not None else None,
                agent_id=step.agent_type,
                attempt_number=attempt.attempt_number,
                status=attempt.status.value,
            )

    # --- Phase A: Knowledge preparation -------------------------------------

    def _phase_a_knowledge(
        self, request: OrchestrationRequest
    ) -> tuple[list[ContractKnowledgeSearchResult], int, bool, RetrievalObservation | None]:
        if self._knowledge_index is None:
            return [], 0, False, None

        query = request.knowledge_query or request.goal
        repository_id = request.repository.repository_id if request.repository else None
        search_request = KnowledgeSearchRequest(query=query, limit=self._knowledge_search_limit)
        base_results = search(self._knowledge_index, search_request)

        adaptive_used = False
        if self._adaptive_retriever is not None:
            ranked = self._adaptive_retriever.retrieve(
                self._knowledge_index,
                search_request,
                task_type=request.task_type,
                repository_id=repository_id,
                production_passports=self._production_retrieval_passports,
            )
            selected_for_context = results_only(ranked)
            adaptive_used = bool(self._adaptive_retriever_policy_enabled())
        else:
            selected_for_context = base_results

        context_result = ContextBuilder().build(selected_for_context, budget=self._context_budget)
        manager_context = build_manager_knowledge_context(self._knowledge_index, context_result)
        observation = build_retrieval_observation(
            query=query,
            task_type=request.task_type,
            repository_id=repository_id,
            agent_type=None,
            base_results=base_results,
            context_result=context_result,
        )
        return manager_context, len(context_result.chunks), adaptive_used, observation

    def _adaptive_retriever_policy_enabled(self) -> bool:
        policy = getattr(self._adaptive_retriever, "_policy", None)
        if isinstance(policy, AdaptiveRetrievalPolicy):
            return policy.enabled
        return self._adaptive_retriever is not None

    # --- Phase B: Manager / Planning -----------------------------------------

    async def _phase_b_manager(
        self,
        request: OrchestrationRequest,
        knowledge_context: list[ContractKnowledgeSearchResult],
    ) -> ManagerOrchestrationResult:
        planning_request = PlanningRequest(
            goal=request.goal,
            repository=request.repository,
            constraints=request.routing_constraints,
            available_capabilities=request.available_capabilities,
            knowledge_context=knowledge_context,
        )
        manager_request = build_manager_request(
            request_id=request.request_id,
            goal=request.goal,
            task_type=request.task_type,
            repository_id=request.repository.repository_id if request.repository else None,
            available_agent_types=request.available_agent_types,
            available_capabilities=request.available_capabilities,
            knowledge_context=knowledge_context,
            workflow_constraints=request.routing_constraints,
            recovery_context=request.recovery_context,
        )
        return await self._manager_orchestrator.orchestrate(
            planning_request=planning_request, manager_request=manager_request
        )

    # --- Phase C: Routing -----------------------------------------------------

    def _phase_c_routing(
        self, request: OrchestrationRequest, plan: WorkflowPlan
    ) -> tuple[dict[str, str], dict[str, "_RoutingContext"]] | None:
        agent_type_by_task_key: dict[str, str] = {}
        routing_context_by_task_key: dict[str, _RoutingContext] = {}
        candidates = self._candidate_provider.candidates()

        def _get_agent_id(c: object) -> str:
            val = (
                getattr(c, "agent_id", None)
                or getattr(c, "agent_type", None)
                or getattr(c, "id", None)
            )
            if not val and hasattr(c, "descriptor") and c.descriptor:
                val = getattr(c.descriptor, "agent_type", None) or getattr(c.descriptor, "id", None)
            return str(val or "")

        if request.available_agent_types:
            avail_set = set(request.available_agent_types)
            candidates = [c for c in candidates if _get_agent_id(c) in avail_set]

        excluded: set[str] = set()
        if request.routing_constraints:
            if isinstance(request.routing_constraints, dict):
                excluded = set(request.routing_constraints.get("excluded_agent_types") or [])
            else:
                rc_excluded = getattr(request.routing_constraints, "excluded_agent_types", [])
                excluded = set(rc_excluded or [])
        if excluded:
            candidates = [c for c in candidates if _get_agent_id(c) not in excluded]

        from app.engine.planning.compiler import (
            CompiledTaskNode,
            ComplexityLevel,
            TargetFileOwnership,
        )
        from app.engine.routing.organization import AgentOrganizationCompiler

        compiled_nodes = []
        for task in plan.tasks:
            payload = task.input_payload or {}
            ownership_str = payload.get("target_files_ownership", "UNKNOWN")
            try:
                ownership = TargetFileOwnership(ownership_str)
            except ValueError:
                ownership = TargetFileOwnership.UNKNOWN

            comp_str = payload.get("estimated_complexity", "SIMPLE")
            try:
                complexity = ComplexityLevel(comp_str)
            except ValueError:
                complexity = ComplexityLevel.SIMPLE

            node = CompiledTaskNode(
                task_id=task.key,
                task_type=task.task_type,
                title=task.name,
                objective=payload.get("objective", task.name),
                dependencies=task.depends_on,
                required_capabilities=task.required_capabilities,
                target_files=payload.get("target_files", []),
                target_files_ownership=ownership,
                parallel_safe=payload.get("parallel_safe", False),
                estimated_complexity=complexity,
                skill_id=payload.get("skill_id"),
                skill_version=payload.get("skill_version"),
                skill_name=payload.get("skill_name"),
                skill_guidance=payload.get("skill_guidance"),
            )
            compiled_nodes.append(node)

        org_compiler = AgentOrganizationCompiler(
            router=self._router,
            skill_agent_intelligence=self._skill_agent_intelligence,
        )
        team = org_compiler.assemble_team(compiled_nodes, candidates)

        if not team.assignments:
            return None

        for task in plan.tasks:
            assignment = team.assignments.get(task.key)
            if not assignment or not assignment.selected_agent_type:
                return None
            agent_type_by_task_key[task.key] = assignment.selected_agent_type
            routing_request = build_routing_request(
                task,
                candidate_agent_types=request.available_agent_types or None,
                constraints=request.routing_constraints,
                repository=request.repository,
            )
            routing_context_by_task_key[task.key] = _RoutingContext(
                request=routing_request, candidates=candidates
            )

        return agent_type_by_task_key, routing_context_by_task_key

    # --- Phase D: Workflow compile + execute -----------------------------------

    async def _phase_d_execute(
        self, plan: WorkflowPlan, agent_type_by_task_key: dict[str, str], execution_id: str
    ) -> tuple[Workflow, dict[str, TaskSpec], dict[str, VerificationResult], list[str]]:
        ordered_tasks = topological_order(plan.tasks)
        workflow_create = compile_workflow_create(plan, agent_type_by_task_key)
        workflow = workflow_service.create_workflow(self._db, workflow_create)

        await self._emit(
            execution_id, OrchestrationEventType.WORKFLOW_CREATED, workflow_id=workflow.id
        )
        await self._emit(
            execution_id, OrchestrationEventType.WORKFLOW_STARTED, workflow_id=workflow.id
        )

        step_to_task = self._map_steps_to_tasks(workflow, ordered_tasks)
        results: dict[str, VerificationResult] = {}
        resolver = self._make_verification_resolver(
            step_to_task, results, execution_id=execution_id
        )

        engine = WorkflowEngine(
            self._db,
            self._registry,
            circuit_breakers=self._circuit_breakers,
            retry_policy=self._retry_policy,
            sleeper=self._sleeper,
            learning_persistence=self._learning_persistence,
            verification_resolver=resolver,
            workspace_root=self._workspace_root,
        )
        watcher = None
        if self._workspace_root:
            from app.services.workspace_watcher import FileActivityEvent, WorkspaceWatcher

            async def _on_file_activity(fa_event: FileActivityEvent) -> None:
                task_spec = step_to_task.get(fa_event.task_id) if fa_event.task_id else None
                t_key = task_spec.key if task_spec else fa_event.task_id
                await self._emit(
                    execution_id,
                    OrchestrationEventType.FILE_ACTIVITY,
                    task_key=t_key,
                    agent_id=fa_event.agent_id,
                    relative_path=fa_event.relative_path,
                    activity=fa_event.activity,
                    message=fa_event.relative_path,
                )

            watcher = WorkspaceWatcher(self._workspace_root, on_activity=_on_file_activity)
            await watcher.start_async()

        task_nodes = getattr(plan, "compiler_nodes", [])
        context = ExecutionContext(
            workflow_id=workflow.id, workflow_input=dict(workflow.input_payload)
        )
        try:
            executed_wf, _timestamps = await engine.execute_workflow_async(
                workflow.id,
                task_nodes,
                context,
                workspace_watcher=watcher,
                max_concurrency=3,
                event_sink=self._event_sink,
                execution_id=execution_id,
                event_sequence=self._event_sequence,
            )
            if watcher is not None:
                watcher.poll_now()
        finally:
            if watcher is not None:
                await watcher.stop_async()

        learning_event_ids = self._collect_learning_event_ids(executed_wf)
        return executed_wf, step_to_task, results, learning_event_ids

    @staticmethod
    def _map_steps_to_tasks(
        workflow: Workflow, ordered_tasks: list[TaskSpec]
    ) -> dict[str, TaskSpec]:
        ordered_steps = sorted(workflow.steps, key=lambda step: step.position)
        return {step.id: task for step, task in zip(ordered_steps, ordered_tasks, strict=True)}

    def _make_verification_resolver(
        self,
        step_to_task: dict[str, TaskSpec],
        results_out: dict[str, VerificationResult],
        execution_id: str = "exec-default",
        attempt_number_offset: int = 0,
    ) -> Callable[[WorkflowStep, StepAttempt], VerificationStatus | None]:
        # Only ever constructed when a real, validated `workspace_root` is
        # present (Stage 8C.3 P1 fix) -- every existing caller/test that
        # never sets `OrchestrationRequest.workspace_root` sees zero
        # behavior change, since `evidence_collector` then stays `None` and
        # `build_observed_outcome` receives exactly the executor's own
        # `output_payload`, unmodified, just as before.
        evidence_collector = (
            WorkspaceEvidenceCollector(self._workspace_root)
            if self._workspace_root is not None
            else None
        )

        def resolver(step: WorkflowStep, attempt: StepAttempt) -> VerificationStatus | None:
            if attempt.status != AttemptStatus.SUCCEEDED:
                return None
            task = step_to_task.get(step.id)
            if task is None:
                return None

            effective_attempt_number = attempt.attempt_number + attempt_number_offset

            result = None
            if task.expected_outcome is not None:
                payload = dict(attempt.output_payload) if attempt.output_payload else {}
                if evidence_collector is not None:
                    # "if trustworthy structured evidence already present:
                    # consume it; else if real workspace execution: collect
                    # objective evidence" -- `collect()` never overwrites a key
                    # `payload` already has.
                    payload.update(evidence_collector.collect(task.expected_outcome, payload))
                observed = build_observed_outcome(payload)
                result = verify_one(
                    task.expected_outcome,
                    observed,
                    verification_id=f"ver-{step.id}-{effective_attempt_number}",
                    workflow_id=step.workflow_id,
                    step_id=step.id,
                    created_at=datetime.now(UTC),
                )

            # Stage 9D Software Quality Factory Verification
            if self._quality_coordinator is not None and self._workspace_root is not None:
                q_context = QualityExecutionContext(
                    workspace_root=self._workspace_root,
                    task_id=task.key,
                    task_type=task.task_type,
                    execution_id=execution_id,
                    agent_id=step.agent_type,
                )
                skill_obj = None
                if self._skill_registry and task.input_payload and "skill_id" in task.input_payload:
                    with contextlib.suppress(Exception):
                        skill_obj = self._skill_registry.get_skill(
                            task.input_payload["skill_id"],
                            task.input_payload.get("skill_version", "1.0.0"),
                        )

                q_verdict, q_run = self._quality_coordinator.verify_software_execution(
                    context=q_context,
                    task=task,
                    skill=skill_obj,
                    workflow_id=step.workflow_id,
                    attempt_number=effective_attempt_number,
                )
                self._quality_runs_by_task_key[task.key] = q_run
                self._last_quality_run = q_run

                if not q_verdict.passed:
                    from app.contracts.enums import BenchmarkEvaluatorType

                    eval_type = (
                        task.expected_outcome.evaluator_type
                        if task.expected_outcome
                        else BenchmarkEvaluatorType.UNIT_TEST
                    )
                    result = VerificationResult(
                        verification_id=f"ver-{step.id}-{effective_attempt_number}",
                        workflow_id=step.workflow_id,
                        step_id=step.id,
                        status=VerificationStatus.FAILED,
                        evaluator_type=eval_type,
                        failure_reason=q_verdict.summary_explanation,
                        created_at=datetime.now(UTC),
                    )

            if result is not None:
                results_out[step.id] = result
                return result.status
            return None

        return resolver

    @staticmethod
    def _collect_learning_event_ids(workflow: Workflow) -> list[str]:
        """Independently recomputes the deterministic event IDs
        `WorkflowEngine`'s own `learning_persistence` wiring already wrote
        (`app.persistence.service.build_event_id`) -- never a second write,
        purely reading back the identity of what was already recorded."""
        ids: list[str] = []
        for step in workflow.steps:
            for attempt in step.attempts:
                if attempt.status in (AttemptStatus.SUCCEEDED, AttemptStatus.FAILED):
                    ids.append(build_event_id(workflow.id, step.id, attempt.attempt_number))
        return ids

    # --- Phase E: Verification + recovery --------------------------------------

    def _phase_e_verify_and_recover(
        self,
        plan: WorkflowPlan,
        workflow: Workflow,
        step_to_task: dict[str, TaskSpec],
        results: dict[str, VerificationResult],
        agent_type_by_task_key: dict[str, str],
        routing_context_by_task_key: dict[str, _RoutingContext],
        learning_event_ids: list[str],
        execution_id: str = "exec-default",
    ) -> tuple[
        Workflow,
        AggregatedVerification | None,
        bool,
        RecoveryAction | None,
        list[str],
        list[tuple[str, str | None, str | None, str]],
    ]:
        aggregated = self._aggregate(results)
        if aggregated is None or aggregated.overall_status == VerificationStatus.PASSED:
            initial_action = RecoveryAction.ACCEPT if aggregated else None
            return workflow, aggregated, False, initial_action, learning_event_ids, []

        current_workflow = workflow
        current_step_to_task = step_to_task
        current_results = results
        current_agent_types = dict(agent_type_by_task_key)
        all_learning_event_ids = list(learning_event_ids)
        recovery_used = False
        attempt_number = 1
        last_action: RecoveryAction | None = None
        current_verification: AggregatedVerification = aggregated
        all_rerouted_tasks: list[tuple[str, str | None, str | None, str]] = []

        while True:
            decision = decide_recovery(
                verification=current_verification,
                attempt_number=attempt_number,
                policy=self._recovery_policy,
            )
            last_action = decision.action
            if decision.action in (
                RecoveryAction.FAIL,
                RecoveryAction.HUMAN_REVIEW,
                RecoveryAction.REQUEST_CONSENSUS,
            ):
                break

            recovery_used = True
            cycle = self._run_recovery_cycle(
                plan,
                current_step_to_task,
                current_results,
                current_agent_types,
                routing_context_by_task_key,
                decision,
                attempt_number,
                execution_id=execution_id,
            )
            if cycle is None:
                last_action = RecoveryAction.FAIL
                break
            (
                current_workflow,
                current_step_to_task,
                current_results,
                new_cycle_agent_types,
                cycle_learning_event_ids,
            ) = cycle
            all_learning_event_ids.extend(cycle_learning_event_ids)
            for t_k, n_agent in new_cycle_agent_types.items():
                p_agent = current_agent_types.get(t_k)
                all_rerouted_tasks.append((t_k, p_agent, n_agent, "verification_failure"))
            current_agent_types = new_cycle_agent_types

            task_key_to_result = {}
            for s_id, t_spec in step_to_task.items():
                if s_id in results:
                    task_key_to_result[t_spec.key] = results[s_id]
            for s_id, t_spec in current_step_to_task.items():
                if s_id in current_results:
                    task_key_to_result[t_spec.key] = current_results[s_id]

            next_verification = self._aggregate(task_key_to_result)
            if next_verification is None:
                # Unreachable in practice (current_results is always
                # non-empty after a successful recovery cycle), but never
                # treated as success if it somehow happened.
                last_action = RecoveryAction.FAIL
                break
            current_verification = next_verification
            if current_verification.overall_status == VerificationStatus.PASSED:
                break
            attempt_number += 1

        return (
            current_workflow,
            current_verification,
            recovery_used,
            last_action,
            all_learning_event_ids,
            all_rerouted_tasks,
        )

    def _run_recovery_cycle(
        self,
        plan: WorkflowPlan,
        step_to_task: dict[str, TaskSpec],
        results: dict[str, VerificationResult],
        agent_type_by_task_key: dict[str, str],
        routing_context_by_task_key: dict[str, _RoutingContext],
        decision: RecoveryDecision,
        attempt_number: int,
        execution_id: str = "exec-default",
    ) -> (
        tuple[
            Workflow, dict[str, TaskSpec], dict[str, VerificationResult], dict[str, str], list[str]
        ]
        | None
    ):
        failed_step_ids = [
            step_id
            for step_id, task in step_to_task.items()
            if step_id in results and results[step_id].status != VerificationStatus.PASSED
        ]
        if not failed_step_ids:
            return None

        failed_tasks = [step_to_task[step_id] for step_id in failed_step_ids]
        # `depends_on` is cleared for the recovery-only compilation: a
        # failed task's TaskSpec.input_payload is static (the current
        # Planner never populates it from another task's runtime output),
        # so re-running just the failed subset independently is correct,
        # and clearing depends_on avoids WorkflowPlan's own "depends on
        # undeclared task" validator rejecting a subset whose dependency
        # already passed and is not being re-run.
        recovery_tasks = [task.model_copy(update={"depends_on": []}) for task in failed_tasks]

        # Stage 9D: Inject structured quality repair packet if available
        if self._quality_coordinator is not None:
            for r_task in recovery_tasks:
                task_qrun = self._quality_runs_by_task_key.get(r_task.key) or self._last_quality_run
                if (
                    task_qrun is not None
                    and task_qrun.verdict is not None
                    and not task_qrun.verdict.passed
                ):
                    repair_packet = self._quality_coordinator.create_repair_packet(
                        task_qrun, max_repair_attempts=self._recovery_policy.max_attempts
                    )
                    if repair_packet:
                        repair_guidance = QualityRepairManager.format_repair_prompt_section(
                            repair_packet
                        )
                        new_payload = dict(r_task.input_payload or {})
                        new_payload["repair_guidance"] = repair_guidance
                        new_payload["repair_packet"] = {
                            "attempt_number": repair_packet.attempt_number,
                            "blocking_gate_ids": list(repair_packet.blocking_gate_ids),
                            "failure_summaries": list(repair_packet.failure_summaries),
                            "diagnostics": list(repair_packet.diagnostics),
                        }
                        r_task.input_payload = new_payload

        new_agent_type_by_task_key: dict[str, str] = {}

        for task, recovery_task in zip(failed_tasks, recovery_tasks, strict=True):
            context = routing_context_by_task_key[task.key]
            if decision.action == RecoveryAction.REROUTE:
                new_decision = reroute(
                    self._router,
                    context.request,
                    context.candidates,
                    additionally_excluded_agent_types=decision.excluded_agent_types,
                )
                if not new_decision.selected_agent_type:
                    return None
                new_agent_type_by_task_key[recovery_task.key] = new_decision.selected_agent_type
            else:  # RETRY_SAME
                new_agent_type_by_task_key[recovery_task.key] = agent_type_by_task_key[task.key]

        recovery_plan = WorkflowPlan(
            plan_id=f"{plan.plan_id}-recovery-{attempt_number}",
            goal=plan.goal,
            tasks=recovery_tasks,
            repository=plan.repository,
            metadata=plan.metadata,
            created_at=plan.created_at,
        )
        recovery_workflow_create = compile_workflow_create(
            recovery_plan,
            new_agent_type_by_task_key,
            name=f"{plan.goal} (recovery attempt {attempt_number + 1})",
        )
        recovery_workflow = workflow_service.create_workflow(self._db, recovery_workflow_create)
        new_step_to_task = self._map_steps_to_tasks(recovery_workflow, recovery_tasks)
        new_results: dict[str, VerificationResult] = {}
        resolver = self._make_verification_resolver(
            new_step_to_task,
            new_results,
            execution_id=execution_id,
            attempt_number_offset=attempt_number,
        )

        engine = WorkflowEngine(
            self._db,
            self._registry,
            circuit_breakers=self._circuit_breakers,
            retry_policy=self._retry_policy,
            sleeper=self._sleeper,
            learning_persistence=self._learning_persistence,
            verification_resolver=resolver,
            workspace_root=self._workspace_root,
        )
        try:
            executed = engine.execute_workflow(recovery_workflow.id)
        except CircuitBreakerOpenError:
            # The breaker opening mid-recovery is a real, safe stop
            # condition -- identical in effect to `reroute()` finding no
            # eligible candidate above (`return None`), not a service
            # failure. Left uncaught, this previously escaped as an
            # unhandled exception all the way to
            # `OrchestrationExecutionCoordinator._run()`'s generic
            # `except Exception`, which reports a bare
            # "CircuitBreakerOpenError: an unexpected internal error
            # occurred" instead of the bounded, already-typed
            # `RecoveryAction.FAIL` outcome this same method already
            # produces for every other "can't recover right now" case.
            logger.warning(
                "recovery_cycle_circuit_breaker_open plan_id=%s attempt_number=%d",
                plan.plan_id,
                attempt_number,
            )
            return None
        learning_event_ids = self._collect_learning_event_ids(executed)
        return (
            executed,
            new_step_to_task,
            new_results,
            new_agent_type_by_task_key,
            learning_event_ids,
        )

    @staticmethod
    def _aggregate(results: dict[str, VerificationResult]) -> AggregatedVerification | None:
        if not results:
            return None
        checks = [CheckOutcome(result=result, required=True) for result in results.values()]
        return aggregate(checks, created_at=datetime.now(UTC))

    # --- Phase G: Retrieval feedback --------------------------------------------

    def _phase_g_feedback(
        self,
        observation: RetrievalObservation | None,
        aggregated: AggregatedVerification | None,
        execution_id: str,
        request: OrchestrationRequest,
    ) -> bool:
        if observation is None or self._retrieval_feedback_repository is None:
            return False
        if aggregated is None:
            return False
        if not observation.selected_chunk_ids:
            return False

        feedback = RetrievalFeedback(
            retrieval_id=observation.retrieval_id,
            chunk_ids=observation.selected_chunk_ids,
            verification_status=aggregated.overall_status,
            task_type=request.task_type,
            repository_id=request.repository.repository_id if request.repository else None,
            evidence_source=EvidenceSource.PRODUCTION,
            execution_id=execution_id,
        )
        self._retrieval_feedback_repository.add(feedback)
        return True

    # --- Skill Foundry: Phase enrichment & verification feedback ------------

    def _enrich_plan_with_skills(
        self, plan: WorkflowPlan, request: OrchestrationRequest, execution_id: str
    ) -> None:
        """Retrieve and attach matching skills to compiled task nodes.

        Invariant: TaskGraphCompiler operates independently of skill availability.
        Skill selection failure degrades gracefully with zero effect on compilation.
        """
        if self._skill_retriever is None:
            return

        ws_context = {
            "languages": getattr(request, "languages", []) or [],
            "frameworks": getattr(request, "frameworks", []) or [],
        }

        for task in plan.tasks:
            try:
                matches = self._skill_retriever.retrieve_skills_for_task(
                    task, workspace_context=ws_context, limit=1
                )
                if matches and matches[0].total_score >= self._skill_retriever.min_score_threshold:
                    matched_skill = matches[0].skill
                    if task.input_payload is None:
                        task.input_payload = {}
                    task.input_payload = attach_skill_to_task_payload(
                        task.input_payload,
                        matched_skill,
                        execution_id=execution_id,
                        task_id=task.key,
                    )
                    task.input_payload["skill_id"] = matched_skill.skill_id
                    task.input_payload["skill_version"] = matched_skill.version
                    task.input_payload["skill_name"] = matched_skill.name
                    if self._skill_adaptive_tracker is not None:
                        from app.engine.skills.adaptive_rag import _compute_task_fingerprint

                        fp = _compute_task_fingerprint(
                            task.task_type,
                            task.input_payload.get("objective", task.name),
                        )
                        self._skill_adaptive_tracker.record_observation(
                            task_fingerprint=fp,
                            task_type=task.task_type,
                            retrieved_skill_ids=tuple(m.skill.skill_id for m in matches),
                            selected_skill_id=matched_skill.skill_id,
                            agent_id=None,
                            execution_id=execution_id,
                            task_id=task.key,
                        )
            except Exception:
                logger.exception("skill_retrieval_failed_for_task task_key=%s", task.key)

    def _record_skill_feedback(
        self,
        workflow: Workflow,
        step_to_task: dict[str, TaskSpec],
        results: dict[str, VerificationResult],
        aggregated: AggregatedVerification | None,
        execution_id: str,
    ) -> None:
        """Persist objective verification evidence for executed skills."""
        if self._skill_evidence_repo is None:
            return

        for step in workflow.steps:
            task = step_to_task.get(step.id)
            if task is None or not task.input_payload:
                continue
            skill_id = task.input_payload.get("skill_id")
            skill_version = task.input_payload.get("skill_version")
            if not skill_id or not skill_version:
                continue

            step_result = results.get(step.id)
            if step_result is not None:
                v_status = step_result.status
                success = v_status is VerificationStatus.PASSED
                failure_cat = step_result.failure_reason
            elif aggregated is not None and aggregated.overall_status is not None:
                v_status = aggregated.overall_status
                success = v_status is VerificationStatus.PASSED
                failure_cat = None
            else:
                v_status = VerificationStatus.INCONCLUSIVE
                success = False
                failure_cat = None

            attempt = max(step.attempts, key=lambda a: a.attempt_number) if step.attempts else None
            latency = (
                (attempt.completed_at - attempt.started_at).total_seconds() * 1000.0
                if (attempt and attempt.started_at and attempt.completed_at)
                else 0.0
            )

            from app.engine.skills.evidence import SkillExecutionEvidence

            evidence = SkillExecutionEvidence(
                skill_id=skill_id,
                skill_version=skill_version,
                task_type=task.task_type,
                agent_id=step.agent_type,
                execution_id=execution_id,
                task_id=task.key,
                verification_status=v_status,
                success=success,
                failure_category=failure_cat,
                latency_ms=latency,
                recovery_required=len(step.attempts) > 1,
            )
            try:
                self._skill_evidence_repo.record_evidence(evidence)
            except Exception:
                logger.exception("failed_to_record_skill_evidence")

            if self._skill_adaptive_tracker is not None:
                from app.engine.skills.adaptive_rag import _compute_task_fingerprint

                fp = _compute_task_fingerprint(
                    task.task_type,
                    task.input_payload.get("objective", task.name),
                )
                try:
                    self._skill_adaptive_tracker.record_feedback(
                        task_fingerprint=fp,
                        task_type=task.task_type,
                        skill_id=skill_id,
                        verification_status=v_status,
                        agent_id=step.agent_type,
                        execution_id=execution_id,
                    )
                except Exception:
                    logger.exception("failed_to_record_skill_adaptive_feedback")

    # --- Shared helpers -----------------------------------------------------

    @staticmethod
    def _determine_outcome(
        aggregated: AggregatedVerification | None, recovery_action: RecoveryAction | None
    ) -> OrchestrationOutcome:
        if aggregated is None:
            return OrchestrationOutcome.RUNTIME_FAILURE
        if aggregated.overall_status == VerificationStatus.PASSED:
            return OrchestrationOutcome.VERIFIED_SUCCESS
        if recovery_action == RecoveryAction.HUMAN_REVIEW:
            return OrchestrationOutcome.HUMAN_REVIEW_REQUIRED
        if recovery_action == RecoveryAction.FAIL:
            return OrchestrationOutcome.RECOVERY_EXHAUSTED
        return OrchestrationOutcome.VERIFICATION_FAILED

    @staticmethod
    def _count_attempts(workflow: Workflow) -> int:
        return sum(len(step.attempts) for step in workflow.steps)

    def _result(
        self,
        request: OrchestrationRequest,
        *,
        outcome: OrchestrationOutcome,
        workflow_id: str | None,
        final_workflow_state: WorkflowStatus | None,
        plan: WorkflowPlan,
        manager_outcome: ManagerOrchestrationResult,
        knowledge_result_count: int,
        adaptive_used: bool,
        warnings: list[str],
        issue_codes: list[str],
        selected_agent_types: tuple[str, ...] = (),
        attempt_count: int = 0,
        verification_status: VerificationStatus | None = None,
        recovery_used: bool = False,
        recovery_action: RecoveryAction | None = None,
        learning_event_ids: list[str] | None = None,
        retrieval_feedback_recorded: bool = False,
    ) -> OrchestrationResult:
        return OrchestrationResult(
            request_id=request.request_id,
            outcome=outcome,
            workflow_id=workflow_id,
            final_workflow_state=final_workflow_state,
            task_count=len(plan.tasks),
            step_count=len(plan.tasks),
            manager_used=manager_outcome.manager_used,
            manager_fallback_used=manager_outcome.fallback_used,
            manager_proposal_validated=manager_outcome.proposal_validated,
            manager_provider_identifier=manager_outcome.manager_identifier,
            knowledge_result_count=knowledge_result_count,
            adaptive_retrieval_used=adaptive_used,
            selected_agent_types=selected_agent_types,
            attempt_count=attempt_count,
            verification_status=verification_status,
            recovery_used=recovery_used,
            recovery_action=recovery_action,
            learning_event_ids=tuple(learning_event_ids or ()),
            retrieval_feedback_recorded=retrieval_feedback_recorded,
            warnings=tuple(warnings),
            issue_codes=tuple(issue_codes),
            quality_run_id=self._last_quality_run.run_id if self._last_quality_run else None,
            quality_verdict_status=(
                self._last_quality_run.verdict.status.value
                if (self._last_quality_run and self._last_quality_run.verdict)
                else None
            ),
        )


__all__ = ["EndToEndOrchestrationService"]
