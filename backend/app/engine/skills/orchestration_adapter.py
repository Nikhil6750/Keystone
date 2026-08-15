"""Stage 9C TaskGraph & Skill Foundry Orchestration Coordinator.

Flow:
1. TaskGraph is compiled independently of skills (works with 0 skills).
2. SkillRetriever selects top matching skill for each task node.
3. SkillAssignment is created and attached to task spec payload.
4. AgentOrganizationCompiler and Router assign agents based on task capabilities.
5. After execution and verification, outcomes feed SkillEvidence and Adaptive RAG utility.
"""

from typing import Any

from app.contracts.planning import TaskSpec
from app.contracts.skills import SkillAssignment, SkillContract
from app.contracts.verification import VerificationStatus
from app.engine.planning.compiler import CompiledTaskNode
from app.engine.skills.adaptive_rag import SkillAdaptiveRAGTracker
from app.engine.skills.agent_intelligence import SkillAgentIntelligenceEngine
from app.engine.skills.evidence import SkillEvidenceRepository, SkillExecutionEvidence
from app.engine.skills.prompt_integration import attach_skill_to_task_payload
from app.engine.skills.registry import SkillRegistry
from app.engine.skills.retriever import SkillRetriever


class SkillOrchestrationCoordinator:
    """Coordinates skill retrieval, assignment, prompt attachment, and outcome feedback."""

    def __init__(
        self,
        registry: SkillRegistry,
        evidence_repo: SkillEvidenceRepository,
        retriever: SkillRetriever | None = None,
        adaptive_rag: SkillAdaptiveRAGTracker | None = None,
        agent_intelligence: SkillAgentIntelligenceEngine | None = None,
    ) -> None:
        self.registry = registry
        self.evidence_repo = evidence_repo
        self.retriever = retriever or SkillRetriever(registry=registry, evidence_repo=evidence_repo)
        self.adaptive_rag = adaptive_rag or SkillAdaptiveRAGTracker()
        self.agent_intelligence = agent_intelligence or SkillAgentIntelligenceEngine(
            evidence_repo=evidence_repo
        )

    def assign_skills_to_tasks(
        self,
        tasks: list[CompiledTaskNode] | list[TaskSpec],
        workspace_context: dict[str, Any] | None = None,
        execution_id: str = "exec-default",
    ) -> dict[str, tuple[SkillContract | None, SkillAssignment | None]]:
        """Retrieve and assign the best matching skill for each task in a task graph.

        Returns {task_id: (SkillContract | None, SkillAssignment | None)}.
        If 0 skills are registered or no skills match, returns None for that task.
        """
        results: dict[str, tuple[SkillContract | None, SkillAssignment | None]] = {}

        for t in tasks:
            task_id = t.task_id if isinstance(t, CompiledTaskNode) else t.key
            task_type = t.task_type
            if isinstance(t, CompiledTaskNode):
                objective = t.objective
            else:
                objective = (t.input_payload or {}).get("objective", t.name)

            matches = self.retriever.retrieve_skills_for_task(
                task=t,
                workspace_context=workspace_context,
                limit=3,
            )

            retrieved_ids = [m.skill.skill_id for m in matches]
            best_match = matches[0] if matches else None
            selected_skill = best_match.skill if best_match else None
            selected_id = selected_skill.skill_id if selected_skill else None

            # Record Adaptive RAG retrieval observation
            self.adaptive_rag.record_observation(
                task_type=task_type,
                objective=objective,
                retrieved_skill_ids=retrieved_ids,
                selected_skill_id=selected_id,
                agent_id=None,  # Not selected yet
                execution_id=execution_id,
                task_id=task_id,
            )

            assignment = None
            if best_match is not None:
                assignment = SkillAssignment(
                    task_id=task_id,
                    skill_id=best_match.skill.skill_id,
                    skill_version=best_match.skill.version,
                    skill_name=best_match.skill.name,
                    category=str(best_match.skill.category),
                    match_score=best_match.total_score,
                    rationale=best_match.explanation,
                )

            results[task_id] = (selected_skill, assignment)

        return results

    def enrich_task_specs_with_skills(
        self,
        task_specs: list[TaskSpec],
        workspace_context: dict[str, Any] | None = None,
        execution_id: str = "exec-default",
    ) -> list[TaskSpec]:
        """Attach skill guidance and provenance to TaskSpecs."""
        assignments = self.assign_skills_to_tasks(
            tasks=task_specs,
            workspace_context=workspace_context,
            execution_id=execution_id,
        )

        enriched: list[TaskSpec] = []
        for spec in task_specs:
            skill, _ = assignments.get(spec.key, (None, None))
            new_payload = attach_skill_to_task_payload(
                input_payload=spec.input_payload or {},
                skill=skill,
                execution_id=execution_id,
                task_id=spec.key,
            )
            enriched.append(
                TaskSpec(
                    key=spec.key,
                    name=spec.name,
                    task_type=spec.task_type,
                    required_capabilities=spec.required_capabilities,
                    depends_on=spec.depends_on,
                    input_payload=new_payload,
                    expected_outcome=spec.expected_outcome,
                )
            )

        return enriched

    def record_execution_outcome(
        self,
        skill_id: str,
        skill_version: str,
        task_type: str,
        agent_id: str,
        execution_id: str,
        task_id: str,
        verification_status: VerificationStatus,
        latency_ms: float = 0.0,
        recovery_required: bool = False,
        failure_category: str | None = None,
        objective: str = "",
    ) -> None:
        """Record objective verification outcome into SkillEvidence and Adaptive RAG."""
        evidence = SkillExecutionEvidence(
            skill_id=skill_id,
            skill_version=skill_version,
            task_type=task_type,
            agent_id=agent_id,
            execution_id=execution_id,
            task_id=task_id,
            verification_status=verification_status,
            success=(verification_status is VerificationStatus.PASSED),
            failure_category=failure_category,
            latency_ms=latency_ms,
            recovery_required=recovery_required,
        )
        self.evidence_repo.record_evidence(evidence)

        # Record Adaptive RAG feedback
        self.adaptive_rag.record_feedback(
            task_type=task_type,
            objective=objective,
            skill_id=skill_id,
            verification_status=verification_status,
            agent_id=agent_id,
            execution_id=execution_id,
        )


__all__ = ["SkillOrchestrationCoordinator"]
