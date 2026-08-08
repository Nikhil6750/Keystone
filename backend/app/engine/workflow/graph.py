"""Workflow DAG: adjacency, cycle detection, ready-step calculation, and
deterministic topological ordering.

`WorkflowDefinition`'s own validators already reject duplicate step keys,
unknown dependencies, and self-dependencies at construction time
(`app.contracts.workflow`); the one structural check that belongs here
instead is cycle detection, since it requires walking the full graph rather
than one step's local fields.
"""

from collections.abc import Collection
from dataclasses import dataclass

from app.contracts.workflow import WorkflowDefinition, WorkflowStepDefinition
from app.engine.workflow.exceptions import CycleDetectedError


@dataclass(frozen=True)
class WorkflowGraph:
    """An immutable, validated view of one `WorkflowDefinition`'s dependency graph."""

    steps: dict[str, WorkflowStepDefinition]
    declaration_order: dict[str, int]
    dependents: dict[str, frozenset[str]]

    @classmethod
    def from_definition(cls, definition: WorkflowDefinition) -> "WorkflowGraph":
        """Build and validate a graph from a workflow definition.

        Raises `CycleDetectedError` if `depends_on` edges form a cycle.
        """
        steps = {step.key: step for step in definition.steps}
        declaration_order = {step.key: index for index, step in enumerate(definition.steps)}

        cycle = _detect_cycle(steps)
        if cycle is not None:
            raise CycleDetectedError(cycle)

        dependents: dict[str, set[str]] = {key: set() for key in steps}
        for step in definition.steps:
            for dependency in step.depends_on:
                dependents[dependency].add(step.key)

        return cls(
            steps=steps,
            declaration_order=declaration_order,
            dependents={key: frozenset(value) for key, value in dependents.items()},
        )

    def ready_steps(self, completed: Collection[str], exclude: Collection[str] = ()) -> list[str]:
        """Steps whose dependencies are all satisfied, not yet completed or excluded.

        Returned in deterministic declaration order, so the same graph and
        the same `completed` set always produce the same scheduling order
        regardless of dict/set iteration order.
        """
        completed_set = set(completed)
        excluded_set = set(exclude)
        ready = [
            key
            for key, step in self.steps.items()
            if key not in completed_set
            and key not in excluded_set
            and all(dependency in completed_set for dependency in step.depends_on)
        ]
        return sorted(ready, key=lambda key: self.declaration_order[key])

    def transitive_dependents(self, key: str) -> set[str]:
        """Every step, direct or indirect, that depends on `key`."""
        result: set[str] = set()
        stack = list(self.dependents.get(key, ()))
        while stack:
            current = stack.pop()
            if current in result:
                continue
            result.add(current)
            stack.extend(self.dependents.get(current, ()))
        return result

    def topological_order(self) -> list[str]:
        """A deterministic topological ordering (Kahn's algorithm, ties broken by
        declaration order)."""
        remaining_indegree = {key: len(step.depends_on) for key, step in self.steps.items()}
        frontier = {key for key, degree in remaining_indegree.items() if degree == 0}
        order: list[str] = []
        while frontier:
            key = min(frontier, key=lambda candidate: self.declaration_order[candidate])
            frontier.remove(key)
            order.append(key)
            for dependent in self.dependents[key]:
                remaining_indegree[dependent] -= 1
                if remaining_indegree[dependent] == 0:
                    frontier.add(dependent)
        return order


def _detect_cycle(steps: dict[str, WorkflowStepDefinition]) -> list[str] | None:
    visiting: set[str] = set()
    visited: set[str] = set()
    path: list[str] = []

    def visit(key: str) -> list[str] | None:
        if key in visiting:
            cycle_start = path.index(key)
            return [*path[cycle_start:], key]
        if key in visited:
            return None
        visiting.add(key)
        path.append(key)
        for dependency in steps[key].depends_on:
            result = visit(dependency)
            if result is not None:
                return result
        path.pop()
        visiting.discard(key)
        visited.add(key)
        return None

    for key in steps:
        if key not in visited:
            found = visit(key)
            if found is not None:
                return found
    return None


__all__ = ["WorkflowGraph"]
