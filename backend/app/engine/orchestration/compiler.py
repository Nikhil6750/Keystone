"""Compiles a Planner `WorkflowPlan` plus a per-task routing decision into
the live, position-ordered `WorkflowCreate` schema (`app.schemas.workflow`)
the real `WorkflowEngine` executes.

Architecture discovery for Stage 8C.1 confirmed this compiler genuinely did
not exist: `WorkflowPlan`/`TaskSpec` (`app.contracts.planning`) are DAG-
shaped (`depends_on`) and carry no `agent_type` (the Planner never selects
a runtime); the live ORM `Workflow`/`WorkflowStep` path
(`app.schemas.workflow.WorkflowCreate`) is strictly position-ordered with
no DAG support at all. `app.contracts.workflow.WorkflowDefinition` is a
separate, still-unwired, in-memory DAG scheduler
(`app.engine.workflow.scheduler.GraphScheduler`) -- not the live engine,
and out of scope here (Part 2's "do not build a second workflow engine").

**Topological compilation, not a new engine.** `WorkflowPlan`'s own
contract-level validator already guarantees `tasks` is cycle-free; this
module only linearizes that already-valid DAG into one dependency-respecting
position order (Kahn's algorithm, lexicographic tie-break on `TaskSpec.key`
for determinism), then hands the ordered, routed tasks to the existing
`WorkflowCreate`/`WorkflowStepCreate` schemas unmodified. No new
scheduling, retry, or state-machine logic is added -- `WorkflowEngine`
still owns all of that once the compiled `WorkflowCreate` is submitted.
"""

from app.contracts.planning import TaskSpec, WorkflowPlan
from app.engine.orchestration.errors import InvalidOrchestrationRequestError
from app.schemas.workflow import WorkflowCreate, WorkflowStepCreate

DEFAULT_STEP_MAX_ATTEMPTS = 3


def topological_order(tasks: list[TaskSpec]) -> list[TaskSpec]:
    """One valid dependency-respecting linear order for `tasks`. `tasks`
    must already be cycle-free (guaranteed by `WorkflowPlan`'s own
    validator for any real `WorkflowPlan.tasks`); this function re-detects
    a cycle defensively and raises rather than silently truncating the
    output if one is somehow present. Deterministic: ties among tasks with
    no remaining unmet dependency are broken lexicographically by `key`.
    """
    by_key = {task.key: task for task in tasks}
    remaining_deps = {task.key: set(task.depends_on) for task in tasks}
    ordered: list[TaskSpec] = []
    available = sorted(key for key, deps in remaining_deps.items() if not deps)

    while available:
        key = available.pop(0)
        ordered.append(by_key[key])
        del remaining_deps[key]
        newly_available = []
        for other_key, deps in remaining_deps.items():
            if key in deps:
                deps.discard(key)
                if not deps:
                    newly_available.append(other_key)
        available = sorted(available + newly_available)

    if len(ordered) != len(tasks):
        stuck = sorted(remaining_deps)
        raise InvalidOrchestrationRequestError(
            f"task graph is not acyclic; cannot topologically order: {stuck}"
        )
    return ordered


def compile_workflow_create(
    plan: WorkflowPlan,
    agent_type_by_task_key: dict[str, str],
    *,
    name: str | None = None,
    max_attempts: int = DEFAULT_STEP_MAX_ATTEMPTS,
) -> WorkflowCreate:
    """Compile `plan.tasks` (topologically ordered) into a `WorkflowCreate`,
    resolving each task's `agent_type` from `agent_type_by_task_key`
    (built by the orchestration service's routing phase -- see
    `service.py`). Raises `InvalidOrchestrationRequestError` if a task has
    no routed agent type; this compiler never invents or defaults one --
    an unroutable task must be caught before compilation is attempted.
    """
    ordered = topological_order(plan.tasks)
    steps: list[WorkflowStepCreate] = []
    for position, task in enumerate(ordered):
        agent_type = agent_type_by_task_key.get(task.key)
        if not agent_type:
            raise InvalidOrchestrationRequestError(
                f"task '{task.key}' has no routed agent_type; cannot compile workflow"
            )
        steps.append(
            WorkflowStepCreate(
                name=task.name,
                position=position,
                agent_type=agent_type,
                input_payload=dict(task.input_payload),
                max_attempts=max_attempts,
            )
        )
    return WorkflowCreate(
        name=name or plan.goal,
        description=plan.goal,
        input_payload={"plan_id": plan.plan_id},
        steps=steps,
    )


__all__ = ["DEFAULT_STEP_MAX_ATTEMPTS", "compile_workflow_create", "topological_order"]
