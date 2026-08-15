"""Stage 4D -- Keystone Deterministic Workflow Planner.

Decides WHAT work needs to happen to accomplish a user goal by decomposing a
`PlanningRequest` into a provider-neutral, dependency-linked `WorkflowPlan`.

Sub-modules:
- `classifier`: Goal category & complexity classification using deterministic rules.
- `templates`: Reusable DAG task templates mapping category/complexity to TaskSpecs.
- `validation`: DAG structural integrity validation (unique keys, cycle detection, etc.).
- `planner`: Core `Planner` orchestrator.
"""

from app.engine.planning.classifier import (
    ClassificationResult,
    ComplexityTier,
    PlanningCategory,
    TaskClassifier,
)
from app.engine.planning.planner import Planner, plan_workflow
from app.engine.planning.templates import TaskTemplate, get_templates_for_plan
from app.engine.planning.validation import PlannerValidationError, validate_task_graph

__all__ = [
    "ClassificationResult",
    "ComplexityTier",
    "Planner",
    "PlannerValidationError",
    "PlanningCategory",
    "TaskClassifier",
    "TaskTemplate",
    "get_templates_for_plan",
    "plan_workflow",
    "validate_task_graph",
]
