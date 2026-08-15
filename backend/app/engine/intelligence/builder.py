"""Stage 9E: `EngineeringIntelligenceGraphBuilder` -- deterministic, idempotent
projection of already-persisted Keystone evidence into the Engineering
Intelligence Graph.

**Architectural boundary, stated plainly**: this module owns no execution
state. It only *reads* already-committed evidence from `Workflow`/
`WorkflowStep`/`StepAttempt` (Stage 2/3) and Stage 9D `QualityRun`s, and
*writes* graph nodes/edges/attributions through
`app.engine.intelligence.graph_repository`. It never mutates a workflow,
step, attempt, or quality run, and a failure anywhere in `ingest_workflow`
is caught and logged, never re-raised -- see `EndToEndOrchestrationService`
for the one production call site (after orchestration's own authoritative
persistence has already completed).

**Idempotency**: every node/edge/attribution id is deterministically
derived from the canonical evidence it projects (see the `_node_id_*`/
`_edge_id`/`_attribution_id` helpers below), and
`IntelligenceGraphRepository.upsert_*` is insert-if-absent, never
update-in-place. Calling `ingest_workflow` twice for the same
`workflow_id` -- whether because the same live orchestration path ran
twice, or because a caller is rebuilding the graph from scratch -- produces
exactly the same rows, never duplicates, and never overwrites a row an
earlier pass already wrote.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.contracts.errors import FailureCategory, classify_legacy_error_type
from app.contracts.intelligence import (
    FailureAttribution,
    FailureAttributionCategory,
    IntelligenceEdge,
    IntelligenceEdgeType,
    IntelligenceNode,
    IntelligenceNodeType,
)
from app.contracts.planning import TaskSpec
from app.contracts.quality import QualityRun, QualityVerdictStatus
from app.engine.intelligence.graph_repository import IntelligenceGraphRepository
from app.engine.quality.repository import QualityRepository
from app.models.enums import AttemptStatus, StepStatus
from app.models.step_attempt import StepAttempt
from app.models.workflow_step import WorkflowStep
from app.services import workflow_service

logger = logging.getLogger(__name__)


# --- Deterministic id derivation -------------------------------------------
# Every helper below is a pure function of stable, already-persisted
# identifiers -- never a timestamp or random value -- so the same source
# evidence always re-derives the same id (see module docstring).


def _node_id(node_type: IntelligenceNodeType, canonical_id: str) -> str:
    return f"node:{node_type.value.lower()}:{canonical_id}"


def _edge_id(edge_type: IntelligenceEdgeType, source_node_id: str, target_node_id: str) -> str:
    return f"edge:{edge_type.value}:{source_node_id}->{target_node_id}"


def _attribution_id(attempt_node_id: str, cause: str) -> str:
    return f"attr:{attempt_node_id}:{cause}"


# Execution-level `FailureCategory` (agent/adapter failure taxonomy,
# `app.contracts.errors`) -> Stage 9E's broader, cross-system
# `FailureAttributionCategory`. Deliberately reuses the existing, already
# certified classification instead of re-deriving one from raw error
# strings a second time.
_FAILURE_CATEGORY_MAP: dict[FailureCategory, FailureAttributionCategory] = {
    FailureCategory.TIMEOUT: FailureAttributionCategory.TIMEOUT,
    FailureCategory.VALIDATION_FAILURE: FailureAttributionCategory.INVALID_CONFIGURATION,
    FailureCategory.CIRCUIT_OPEN: FailureAttributionCategory.AGENT_UNAVAILABLE,
    FailureCategory.PROVIDER_ERROR: FailureAttributionCategory.AGENT_UNAVAILABLE,
    FailureCategory.NETWORK_ERROR: FailureAttributionCategory.AGENT_UNAVAILABLE,
    FailureCategory.AUTHENTICATION_FAILURE: FailureAttributionCategory.AGENT_UNAVAILABLE,
    FailureCategory.RATE_LIMITED: FailureAttributionCategory.AGENT_UNAVAILABLE,
    FailureCategory.RESOURCE_EXHAUSTED: FailureAttributionCategory.EXECUTION_FAILURE,
    FailureCategory.INTERNAL_ERROR: FailureAttributionCategory.EXECUTION_FAILURE,
    FailureCategory.CANCELLED: FailureAttributionCategory.EXECUTION_FAILURE,
    FailureCategory.UNKNOWN: FailureAttributionCategory.UNKNOWN,
}


@dataclass(frozen=True)
class IngestionSummary:
    """Deterministic, factual outcome of one `ingest_workflow` call."""

    workflow_id: str
    found: bool
    nodes_created: int = 0
    edges_created: int = 0
    attributions_created: int = 0
    quality_runs_linked: int = 0
    quality_runs_unlinked: int = 0
    errors: tuple[str, ...] = field(default_factory=tuple)


class EngineeringIntelligenceGraphBuilder:
    """Projects one workflow's authoritative execution + quality evidence
    into the Engineering Intelligence Graph.

    `ingest_workflow` is the single ingestion entry point, used identically
    by the live production hook (`EndToEndOrchestrationService.orchestrate`)
    and by any offline rebuild -- see module docstring.
    """

    def __init__(
        self,
        graph_repo: IntelligenceGraphRepository,
        db_session_factory: Callable[[], Session],
        quality_repository: QualityRepository | None = None,
    ) -> None:
        self._graph_repo = graph_repo
        self._db_session_factory = db_session_factory
        self._quality_repository = quality_repository

    def ingest_workflow(
        self,
        workflow_id: str,
        *,
        step_to_task: dict[str, TaskSpec] | None = None,
    ) -> IngestionSummary:
        """Project `workflow_id`'s persisted workflow/step/attempt evidence
        (plus any linked Stage 9D quality runs) into the graph. Never
        raises: any failure is caught, logged, and reported in the returned
        summary's `errors`, so a caller (the live orchestration hook, or a
        batch rebuild loop) can safely call this for many workflows without
        one bad workflow aborting the rest."""
        try:
            with self._db_session_factory() as session:
                workflow = workflow_service.get_workflow(session, workflow_id)
                if workflow is None:
                    return IngestionSummary(workflow_id=workflow_id, found=False)

                nodes_created = 0
                edges_created = 0

                def _upsert_node(node: IntelligenceNode) -> None:
                    nonlocal nodes_created
                    if self._graph_repo.upsert_node(node):
                        nodes_created += 1

                def _upsert_edge(edge: IntelligenceEdge) -> None:
                    nonlocal edges_created
                    if self._graph_repo.upsert_edge(edge):
                        edges_created += 1

                wf_node_id = _node_id(IntelligenceNodeType.WORKFLOW, workflow.id)
                _upsert_node(
                    IntelligenceNode(
                        node_id=wf_node_id,
                        node_type=IntelligenceNodeType.WORKFLOW,
                        canonical_id=workflow.id,
                        label=workflow.name,
                        workflow_id=workflow.id,
                        status=str(workflow.status.value)
                        if hasattr(workflow.status, "value")
                        else str(workflow.status),
                    )
                )

                quality_runs = self._load_quality_runs_by_workflow(workflow_id)
                quality_runs_linked = 0

                attributions_created = 0

                for step in sorted(workflow.steps, key=lambda s: s.position):
                    task = step_to_task.get(step.id) if step_to_task else None
                    task_type = task.task_type if task is not None else (
                        step.input_payload.get("task_type")
                        if isinstance(step.input_payload, dict)
                        else None
                    )
                    skill_id = (
                        step.input_payload.get("skill_id")
                        if isinstance(step.input_payload, dict)
                        else None
                    )
                    skill_version = (
                        step.input_payload.get("skill_version")
                        if isinstance(step.input_payload, dict)
                        else None
                    )

                    task_node_id = _node_id(IntelligenceNodeType.TASK, step.id)
                    _upsert_node(
                        IntelligenceNode(
                            node_id=task_node_id,
                            node_type=IntelligenceNodeType.TASK,
                            canonical_id=step.id,
                            label=step.name,
                            workflow_id=workflow.id,
                            agent_type=step.agent_type,
                            task_type=task_type if isinstance(task_type, str) else None,
                            skill_id=skill_id if isinstance(skill_id, str) else None,
                            skill_version=skill_version if isinstance(skill_version, str) else None,
                            status=str(step.status.value)
                            if hasattr(step.status, "value")
                            else str(step.status),
                        )
                    )
                    _upsert_edge(
                        IntelligenceEdge(
                            edge_id=_edge_id(
                                IntelligenceEdgeType.WORKFLOW_CONTAINS_TASK,
                                wf_node_id,
                                task_node_id,
                            ),
                            edge_type=IntelligenceEdgeType.WORKFLOW_CONTAINS_TASK,
                            source_node_id=wf_node_id,
                            target_node_id=task_node_id,
                        )
                    )

                    agent_node_id = _node_id(IntelligenceNodeType.AGENT, step.agent_type)
                    _upsert_node(
                        IntelligenceNode(
                            node_id=agent_node_id,
                            node_type=IntelligenceNodeType.AGENT,
                            canonical_id=step.agent_type,
                            label=step.agent_type,
                            agent_type=step.agent_type,
                        )
                    )
                    _upsert_edge(
                        IntelligenceEdge(
                            edge_id=_edge_id(
                                IntelligenceEdgeType.TASK_EXECUTED_BY_AGENT,
                                task_node_id,
                                agent_node_id,
                            ),
                            edge_type=IntelligenceEdgeType.TASK_EXECUTED_BY_AGENT,
                            source_node_id=task_node_id,
                            target_node_id=agent_node_id,
                        )
                    )

                    if isinstance(skill_id, str) and isinstance(skill_version, str):
                        skill_node_id = _node_id(
                            IntelligenceNodeType.SKILL_VERSION, f"{skill_id}:{skill_version}"
                        )
                        _upsert_node(
                            IntelligenceNode(
                                node_id=skill_node_id,
                                node_type=IntelligenceNodeType.SKILL_VERSION,
                                canonical_id=f"{skill_id}:{skill_version}",
                                label=f"{skill_id} v{skill_version}",
                                skill_id=skill_id,
                                skill_version=skill_version,
                            )
                        )
                        _upsert_edge(
                            IntelligenceEdge(
                                edge_id=_edge_id(
                                    IntelligenceEdgeType.TASK_USED_SKILL,
                                    task_node_id,
                                    skill_node_id,
                                ),
                                edge_type=IntelligenceEdgeType.TASK_USED_SKILL,
                                source_node_id=task_node_id,
                                target_node_id=skill_node_id,
                            )
                        )

                    ordered_attempts = sorted(step.attempts, key=lambda a: a.attempt_number)
                    if task is not None:
                        # Exact correlation: the live production caller
                        # (`EndToEndOrchestrationService`) has the real
                        # `TaskSpec`, and Stage 9D's `QualityExecutionContext
                        # .task_id` is always set to `task.key` -- no
                        # ambiguity possible even when several steps in the
                        # same workflow share one agent_type/attempt_number.
                        step_quality_runs = [r for r in quality_runs if r.task_id == task.key]
                    else:
                        # Rebuild-from-persistence-only fallback: `task.key`
                        # is never itself persisted on `WorkflowStep`, so the
                        # best available evidence is
                        # (agent_type, attempt_number) -- deliberately only
                        # used when it uniquely identifies one attempt (see
                        # the `len(matching_runs) == 1` check below); an
                        # ambiguous match is left unlinked rather than
                        # guessed.
                        step_quality_runs = [
                            r
                            for r in quality_runs
                            if r.agent_id == step.agent_type
                            and any(a.attempt_number == r.attempt_number for a in ordered_attempts)
                        ]

                    for idx, attempt in enumerate(ordered_attempts):
                        attempt_node_id = self._ingest_attempt(
                            task_node_id=task_node_id,
                            step=step,
                            attempt=attempt,
                            task_type=task_type if isinstance(task_type, str) else None,
                            skill_id=skill_id if isinstance(skill_id, str) else None,
                            skill_version=skill_version if isinstance(skill_version, str) else None,
                            upsert_node=_upsert_node,
                            upsert_edge=_upsert_edge,
                        )

                        matching_runs = [
                            r
                            for r in step_quality_runs
                            if r.attempt_number == attempt.attempt_number
                        ]
                        if len(matching_runs) == 1:
                            self._ingest_quality_run(
                                attempt_node_id=attempt_node_id,
                                run=matching_runs[0],
                                task_type=task_type if isinstance(task_type, str) else None,
                                agent_type=step.agent_type,
                                skill_id=skill_id if isinstance(skill_id, str) else None,
                                upsert_node=_upsert_node,
                                upsert_edge=_upsert_edge,
                            )
                            quality_runs_linked += 1
                            if not matching_runs[0].verdict or not matching_runs[0].verdict.passed:
                                attribution = self._quality_failure_attribution(
                                    attempt_node_id=attempt_node_id,
                                    run=matching_runs[0],
                                    workflow_id=workflow.id,
                                    agent_type=step.agent_type,
                                    task_type=task_type if isinstance(task_type, str) else None,
                                    skill_id=skill_id if isinstance(skill_id, str) else None,
                                )
                                if self._graph_repo.upsert_failure_attribution(attribution):
                                    attributions_created += 1

                        if attempt.status == AttemptStatus.FAILED:
                            is_final_attempt = idx == len(ordered_attempts) - 1
                            attribution = self._execution_failure_attribution(
                                attempt_node_id=attempt_node_id,
                                attempt=attempt,
                                step=step,
                                workflow_id=workflow.id,
                                task_type=task_type if isinstance(task_type, str) else None,
                                skill_id=skill_id if isinstance(skill_id, str) else None,
                                is_final_attempt=is_final_attempt,
                            )
                            if self._graph_repo.upsert_failure_attribution(attribution):
                                attributions_created += 1

                        has_next_attempt = idx + 1 < len(ordered_attempts)
                        if has_next_attempt and attempt.status == AttemptStatus.FAILED:
                            recovering_attempt = ordered_attempts[idx + 1]
                            self._ingest_recovery(
                                failed_attempt_node_id=attempt_node_id,
                                recovering_attempt=recovering_attempt,
                                task_node_id=task_node_id,
                                upsert_node=_upsert_node,
                                upsert_edge=_upsert_edge,
                            )

                quality_runs_unlinked = len(quality_runs) - quality_runs_linked

                return IngestionSummary(
                    workflow_id=workflow_id,
                    found=True,
                    nodes_created=nodes_created,
                    edges_created=edges_created,
                    attributions_created=attributions_created,
                    quality_runs_linked=quality_runs_linked,
                    quality_runs_unlinked=max(0, quality_runs_unlinked),
                )
        except Exception as exc:  # pragma: no cover - defensive, see docstring
            logger.exception(
                "engineering_intelligence_ingestion_failed workflow_id=%s", workflow_id
            )
            return IngestionSummary(workflow_id=workflow_id, found=True, errors=(str(exc),))

    # --- Per-attempt projection ---------------------------------------------

    def _ingest_attempt(
        self,
        *,
        task_node_id: str,
        step: WorkflowStep,
        attempt: StepAttempt,
        task_type: str | None,
        skill_id: str | None,
        skill_version: str | None,
        upsert_node: Callable[[IntelligenceNode], None],
        upsert_edge: Callable[[IntelligenceEdge], None],
    ) -> str:
        attempt_node_id = _node_id(IntelligenceNodeType.ATTEMPT, attempt.id)
        status_value = (
            attempt.status.value if hasattr(attempt.status, "value") else str(attempt.status)
        )
        upsert_node(
            IntelligenceNode(
                node_id=attempt_node_id,
                node_type=IntelligenceNodeType.ATTEMPT,
                canonical_id=attempt.id,
                label=f"attempt #{attempt.attempt_number}",
                workflow_id=step.workflow_id,
                agent_type=step.agent_type,
                task_type=task_type,
                skill_id=skill_id,
                skill_version=skill_version,
                status=status_value,
                metadata={"attempt_number": attempt.attempt_number},
            )
        )
        upsert_edge(
            IntelligenceEdge(
                edge_id=_edge_id(
                    IntelligenceEdgeType.TASK_HAS_ATTEMPT, task_node_id, attempt_node_id
                ),
                edge_type=IntelligenceEdgeType.TASK_HAS_ATTEMPT,
                source_node_id=task_node_id,
                target_node_id=attempt_node_id,
            )
        )

        outcome_node_id = _node_id(
            IntelligenceNodeType.OUTCOME, f"{attempt.id}:{status_value}"
        )
        upsert_node(
            IntelligenceNode(
                node_id=outcome_node_id,
                node_type=IntelligenceNodeType.OUTCOME,
                canonical_id=attempt.id,
                label=status_value,
                workflow_id=step.workflow_id,
                agent_type=step.agent_type,
                task_type=task_type,
                skill_id=skill_id,
                skill_version=skill_version,
                status=status_value,
            )
        )
        upsert_edge(
            IntelligenceEdge(
                edge_id=_edge_id(
                    IntelligenceEdgeType.ATTEMPT_PRODUCED_OUTCOME, attempt_node_id, outcome_node_id
                ),
                edge_type=IntelligenceEdgeType.ATTEMPT_PRODUCED_OUTCOME,
                source_node_id=attempt_node_id,
                target_node_id=outcome_node_id,
            )
        )

        if attempt.status == AttemptStatus.FAILED:
            failure_node_id = _node_id(IntelligenceNodeType.FAILURE, f"{attempt.id}:execution")
            upsert_node(
                IntelligenceNode(
                    node_id=failure_node_id,
                    node_type=IntelligenceNodeType.FAILURE,
                    canonical_id=attempt.id,
                    label=attempt.error_type or "execution_failure",
                    workflow_id=step.workflow_id,
                    agent_type=step.agent_type,
                    task_type=task_type,
                    skill_id=skill_id,
                    skill_version=skill_version,
                    metadata={"error_type": attempt.error_type},
                )
            )
            upsert_edge(
                IntelligenceEdge(
                    edge_id=_edge_id(
                        IntelligenceEdgeType.ATTEMPT_FAILED_WITH, attempt_node_id, failure_node_id
                    ),
                    edge_type=IntelligenceEdgeType.ATTEMPT_FAILED_WITH,
                    source_node_id=attempt_node_id,
                    target_node_id=failure_node_id,
                )
            )

        return attempt_node_id

    def _ingest_recovery(
        self,
        *,
        failed_attempt_node_id: str,
        recovering_attempt: StepAttempt,
        task_node_id: str,
        upsert_node: Callable[[IntelligenceNode], None],
        upsert_edge: Callable[[IntelligenceEdge], None],
    ) -> None:
        recovering_attempt_node_id = _node_id(
            IntelligenceNodeType.ATTEMPT, recovering_attempt.id
        )
        recovery_node_id = _node_id(
            IntelligenceNodeType.RECOVERY_ATTEMPT,
            f"{failed_attempt_node_id}->{recovering_attempt.id}",
        )
        status_value = (
            recovering_attempt.status.value
            if hasattr(recovering_attempt.status, "value")
            else str(recovering_attempt.status)
        )
        upsert_node(
            IntelligenceNode(
                node_id=recovery_node_id,
                node_type=IntelligenceNodeType.RECOVERY_ATTEMPT,
                canonical_id=recovering_attempt.id,
                label=f"recovery via attempt #{recovering_attempt.attempt_number}",
                status=status_value,
                metadata={"recovering_attempt_node_id": recovering_attempt_node_id},
            )
        )
        upsert_edge(
            IntelligenceEdge(
                edge_id=_edge_id(
                    IntelligenceEdgeType.ATTEMPT_RECOVERED_BY,
                    failed_attempt_node_id,
                    recovery_node_id,
                ),
                edge_type=IntelligenceEdgeType.ATTEMPT_RECOVERED_BY,
                source_node_id=failed_attempt_node_id,
                target_node_id=recovery_node_id,
            )
        )
        upsert_edge(
            IntelligenceEdge(
                edge_id=_edge_id(
                    IntelligenceEdgeType.TASK_HAS_ATTEMPT, task_node_id, recovering_attempt_node_id
                ),
                edge_type=IntelligenceEdgeType.TASK_HAS_ATTEMPT,
                source_node_id=task_node_id,
                target_node_id=recovering_attempt_node_id,
            )
        )

    # --- Quality run projection ----------------------------------------------

    def _ingest_quality_run(
        self,
        *,
        attempt_node_id: str,
        run: QualityRun,
        task_type: str | None,
        agent_type: str | None,
        skill_id: str | None,
        upsert_node: Callable[[IntelligenceNode], None],
        upsert_edge: Callable[[IntelligenceEdge], None],
    ) -> None:
        run_node_id = _node_id(IntelligenceNodeType.QUALITY_RUN, run.run_id)
        verdict_status = run.verdict.status.value if run.verdict else None
        upsert_node(
            IntelligenceNode(
                node_id=run_node_id,
                node_type=IntelligenceNodeType.QUALITY_RUN,
                canonical_id=run.run_id,
                label=f"quality run {run.run_id}",
                workflow_id=run.workflow_id,
                agent_type=agent_type,
                task_type=task_type,
                skill_id=skill_id,
                skill_version=run.skill_version,
                status=verdict_status,
                metadata={
                    "passed": run.verdict.passed if run.verdict else None,
                    "attempt_number": run.attempt_number,
                },
            )
        )
        upsert_edge(
            IntelligenceEdge(
                edge_id=_edge_id(
                    IntelligenceEdgeType.ATTEMPT_HAS_QUALITY_RUN, attempt_node_id, run_node_id
                ),
                edge_type=IntelligenceEdgeType.ATTEMPT_HAS_QUALITY_RUN,
                source_node_id=attempt_node_id,
                target_node_id=run_node_id,
            )
        )

        for gate in run.gate_results:
            gate_canonical_id = f"{run.run_id}:{gate.gate_id}"
            gate_node_id = _node_id(IntelligenceNodeType.QUALITY_GATE, gate_canonical_id)
            gate_type_value = (
                gate.gate_type.value if hasattr(gate.gate_type, "value") else str(gate.gate_type)
            )
            gate_status_value = (
                gate.status.value if hasattr(gate.status, "value") else str(gate.status)
            )
            upsert_node(
                IntelligenceNode(
                    node_id=gate_node_id,
                    node_type=IntelligenceNodeType.QUALITY_GATE,
                    canonical_id=gate_canonical_id,
                    label=gate.name,
                    workflow_id=run.workflow_id,
                    agent_type=agent_type,
                    task_type=task_type,
                    skill_id=skill_id,
                    status=gate_status_value,
                    metadata={
                        "gate_type": gate_type_value,
                        "required": gate.required,
                    },
                )
            )
            upsert_edge(
                IntelligenceEdge(
                    edge_id=_edge_id(
                        IntelligenceEdgeType.QUALITY_RUN_EXECUTED_GATE, run_node_id, gate_node_id
                    ),
                    edge_type=IntelligenceEdgeType.QUALITY_RUN_EXECUTED_GATE,
                    source_node_id=run_node_id,
                    target_node_id=gate_node_id,
                )
            )

    # --- Failure attribution ---------------------------------------------------

    def _execution_failure_attribution(
        self,
        *,
        attempt_node_id: str,
        attempt: StepAttempt,
        step: WorkflowStep,
        workflow_id: str,
        task_type: str | None,
        skill_id: str | None,
        is_final_attempt: bool,
    ) -> FailureAttribution:
        # A step that exhausted every configured attempt without succeeding
        # is direct, persisted evidence of recovery exhaustion (StepStatus
        # itself reached FAILED, and more than one attempt was actually
        # made) -- distinct from a single retryable failure mid-retry.
        if (
            is_final_attempt
            and StepStatus(step.status) is StepStatus.FAILED
            and step.attempt_count > 1
        ):
            return FailureAttribution(
                attribution_id=_attribution_id(attempt_node_id, "execution"),
                attempt_node_id=attempt_node_id,
                category=FailureAttributionCategory.RECOVERY_EXHAUSTION,
                is_known=True,
                explanation=(
                    f"step exhausted all {step.attempt_count} configured attempt(s) "
                    "without a successful execution"
                ),
                evidence_ids=(attempt.id, step.id),
                workflow_id=workflow_id,
                agent_type=step.agent_type,
                task_type=task_type,
                skill_id=skill_id,
            )

        legacy_category = (
            classify_legacy_error_type(attempt.error_type) if attempt.error_type else None
        )
        category = (
            _FAILURE_CATEGORY_MAP.get(legacy_category, FailureAttributionCategory.UNKNOWN)
            if legacy_category is not None
            else FailureAttributionCategory.UNKNOWN
        )
        is_known = category is not FailureAttributionCategory.UNKNOWN
        explanation = (
            f"execution attempt failed with error_type={attempt.error_type!r}: "
            f"{attempt.error_message or 'no message recorded'}"
            if attempt.error_type
            else "execution attempt failed with no recorded error_type"
        )
        return FailureAttribution(
            attribution_id=_attribution_id(attempt_node_id, "execution"),
            attempt_node_id=attempt_node_id,
            category=category,
            is_known=is_known,
            explanation=explanation,
            evidence_ids=(attempt.id,),
            workflow_id=workflow_id,
            agent_type=step.agent_type,
            task_type=task_type,
            skill_id=skill_id,
        )

    def _quality_failure_attribution(
        self,
        *,
        attempt_node_id: str,
        run: QualityRun,
        workflow_id: str,
        agent_type: str,
        task_type: str | None,
        skill_id: str | None,
    ) -> FailureAttribution:
        blocking_gate_ids = (
            tuple(g.gate_id for g in run.verdict.blocking_failures) if run.verdict else ()
        )
        # A task with a linked skill whose Stage 9D verdict rejected the
        # execution is direct evidence the skill's own verification
        # contract was not satisfied -- distinct from a generic quality
        # gate failure with no skill involvement.
        category = (
            FailureAttributionCategory.SKILL_VERIFICATION_FAILURE
            if skill_id
            else FailureAttributionCategory.QUALITY_GATE_FAILURE
        )
        status_value = (
            run.verdict.status.value if run.verdict else QualityVerdictStatus.REJECTED.value
        )
        explanation = (
            run.verdict.summary_explanation
            if run.verdict
            else f"quality run '{run.run_id}' produced no verdict"
        )
        return FailureAttribution(
            attribution_id=_attribution_id(attempt_node_id, "quality"),
            attempt_node_id=attempt_node_id,
            category=category,
            is_known=True,
            explanation=f"quality verdict status={status_value}: {explanation}",
            evidence_ids=(run.run_id, *blocking_gate_ids),
            workflow_id=workflow_id,
            agent_type=agent_type,
            task_type=task_type,
            skill_id=skill_id,
        )

    def _load_quality_runs_by_workflow(self, workflow_id: str) -> list[QualityRun]:
        if self._quality_repository is None:
            return []
        try:
            return self._quality_repository.get_runs_by_workflow(workflow_id)
        except Exception:
            logger.exception(
                "engineering_intelligence_quality_run_lookup_failed workflow_id=%s", workflow_id
            )
            return []


__all__ = ["EngineeringIntelligenceGraphBuilder", "IngestionSummary"]
