"""Translates a Planner's `TaskSpec` into a `RoutingRequest` the Router can
evaluate.

`TaskSpec.task_type` is authoritative here and used as-is — this module
never re-classifies it. `RuleBasedTaskClassifier` (`classifier.py`) is a
separate, independent fallback for callers that only have raw, unstructured
task text and no `TaskSpec` yet; nothing in this stage calls it (there is no
such caller until a Planner exists), but it's exposed as
`classify_task_type` for that future path. This module does not decompose
goals, invent task structure, or choose an agent — that remains the
Planner's and Router's job respectively.
"""

from app.contracts.adapter import RepositoryMetadata
from app.contracts.planning import TaskSpec
from app.contracts.routing import RoutingConstraints, RoutingRequest
from app.engine.routing.classifier import RuleBasedTaskClassifier, TaskClassifier


def build_routing_request(
    task: TaskSpec,
    *,
    candidate_agent_types: list[str] | None = None,
    constraints: RoutingConstraints | None = None,
    repository: RepositoryMetadata | None = None,
    manual_override_agent_type: str | None = None,
) -> RoutingRequest:
    """Build a `RoutingRequest` for one Planner-produced `TaskSpec`.

    `task.task_type` and `task.required_capabilities` map straight across —
    no classification, capability inference, or natural-language parsing
    happens here. `constraints` defaults to a permissive `RoutingConstraints`
    (matching `RoutingRequest`'s own default) when the caller has none to
    supply yet (e.g. no `PlanningRequest.constraints` was set).
    """
    return RoutingRequest(
        task_type=task.task_type,
        repository=repository,
        required_capabilities=list(task.required_capabilities),
        candidate_agent_types=candidate_agent_types,
        manual_override_agent_type=manual_override_agent_type,
        constraints=constraints if constraints is not None else RoutingConstraints(),
    )


def classify_task_type(description: str, classifier: TaskClassifier | None = None) -> str:
    """Fallback task-type classification for raw, unstructured task text with
    no `TaskSpec` yet. Never used when a `TaskSpec` is already available —
    `task.task_type` is authoritative in that case; see `build_routing_request`.
    """
    return (classifier or RuleBasedTaskClassifier()).classify(description)


__all__ = ["build_routing_request", "classify_task_type"]
