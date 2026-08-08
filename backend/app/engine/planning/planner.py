"""Deterministic Workflow Planner for Stage 4D.

Decomposes a user `PlanningRequest` into an ordered, dependency-linked `WorkflowPlan`.
Operates purely deterministically using rule-based classification and reusable DAG task templates.
Does NOT invoke LLMs, does NOT assign agent_type to TaskSpec, and does NOT call the Router.
"""

import hashlib
from datetime import UTC, datetime
from typing import Any

from app.contracts.planning import PlanningRequest, TaskSpec, WorkflowPlan
from app.engine.planning.classifier import TaskClassifier
from app.engine.planning.templates import get_templates_for_plan
from app.engine.planning.validation import validate_task_graph


class Planner:
    """Deterministic, provider-neutral Workflow Planner."""

    def __init__(self, classifier: TaskClassifier | None = None) -> None:
        self.classifier = classifier or TaskClassifier()

    def plan(self, request: PlanningRequest) -> WorkflowPlan:
        """Decompose a PlanningRequest into a deterministic WorkflowPlan.

        Produces identical output for identical input (same plan_id, same tasks,
        same ordering, same capabilities, same dependencies, same expected outcomes).
        """
        # 1. Deterministic Goal Classification & Complexity Assessment
        classification = self.classifier.classify(request.goal)

        # 2. Select Template for (Category, ComplexityTier)
        templates = get_templates_for_plan(
            classification.category, classification.complexity_tier
        )

        # 3. Knowledge Context Privacy (Opaque metadata only -- no raw snippets, contents, or paths)
        knowledge_titles: list[str] = []
        for item in request.knowledge_context:
            if item.title and item.title.strip():
                knowledge_titles.append(item.title.strip())

        # 4. Generate Provider-Neutral TaskSpecs
        tasks: list[TaskSpec] = []
        for tmpl in templates:
            task_spec = tmpl.build_task_spec(request.goal)
            tasks.append(task_spec)

        # 5. Validate Task Graph (Delegated to WorkflowPlan contract source of truth)
        validate_task_graph(tasks)

        tmpl_suffix = classification.complexity_tier.value.lower()
        plan_metadata: dict[str, Any] = {
            "plan_category": classification.category.value,
            "complexity_tier": classification.complexity_tier.value,
            "template_name": f"{classification.category.value}_{tmpl_suffix}",
            "rule_identifiers": classification.rule_identifiers,
            "normalized_goal": classification.normalized_goal,
        }
        if knowledge_titles:
            plan_metadata["knowledge_context_count"] = len(knowledge_titles)
            plan_metadata["knowledge_context_titles"] = knowledge_titles

        if request.metadata:
            # Preserve request metadata non-destructively
            for k, v in request.metadata.items():
                if k not in plan_metadata:
                    plan_metadata[k] = v

        # 7. Compute Deterministic plan_id and Timestamp
        repo_name = (
            request.repository.name
            if request.repository and request.repository.name
            else ""
        )
        plan_id = self._compute_deterministic_plan_id(
            goal=classification.normalized_goal,
            category=classification.category.value,
            complexity=classification.complexity_tier.value,
            repo_name=repo_name,
            tasks=[t.key for t in tasks],
        )

        # Fixed UTC epoch timestamp ensures 100% bit-for-bit determinism across plan invocations
        created_at = datetime(1970, 1, 1, 0, 0, 0, tzinfo=UTC)

        return WorkflowPlan(
            plan_id=plan_id,
            goal=request.goal,
            tasks=tasks,
            repository=request.repository,
            metadata=plan_metadata,
            created_at=created_at,
        )

    @staticmethod
    def _compute_deterministic_plan_id(
        goal: str, category: str, complexity: str, repo_name: str, tasks: list[str]
    ) -> str:
        """Compute SHA-256 hash for deterministic plan identity."""
        raw_payload = f"{goal}|{category}|{complexity}|{repo_name}|{','.join(tasks)}"
        digest = hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()[:16]
        return f"plan_{digest}"


def plan_workflow(
    request: PlanningRequest, planner: Planner | None = None
) -> WorkflowPlan:
    """Public helper to decompose a PlanningRequest into a WorkflowPlan."""
    p = planner or Planner()
    return p.plan(request)


__all__ = ["Planner", "plan_workflow"]
