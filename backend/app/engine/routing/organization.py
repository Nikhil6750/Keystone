"""Agent Organization Compiler.

Assembles execution teams dynamically by mapping compiled tasks to candidate agents.
Selects effective teams (e.g. 1 agent for sequential graphs, distinct agents for parallel tasks).
Does NOT use hardcoded provider rules; respects eligibility hard filters and router scoring.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.routing import RoutingRequest
from app.engine.planning.compiler import CompiledTaskNode
from app.engine.routing.availability import CandidateAgent
from app.engine.routing.router import Router


class TaskAssignment(BaseModel):
    """Assignment decision for a single task."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    selected_agent_type: str | None = None
    fallback_order: list[str] = Field(default_factory=list)


class TeamAssignment(BaseModel):
    """Execution team assignment decision for an entire task graph."""

    model_config = ConfigDict(extra="forbid")

    assignments: dict[str, TaskAssignment] = Field(default_factory=dict)
    selected_agent_ids: list[str] = Field(default_factory=list)


class AgentOrganizationCompiler:
    """Assembles an effective agent execution team for a task graph."""

    def __init__(self, router: Router | None = None) -> None:
        self.router = router or Router()

    def assemble_team(
        self,
        tasks: list[CompiledTaskNode],
        candidates: list[CandidateAgent],
    ) -> TeamAssignment:
        """Assemble an agent team for the given tasks from available candidates."""
        if not tasks:
            return TeamAssignment()

        # 1. Filter candidates to eligible ones
        from app.contracts.enums import AgentStatus
        from app.resilience.circuit_breaker import CircuitState

        eligible_candidates = [
            c for c in candidates
            if c.status in (AgentStatus.AVAILABLE, AgentStatus.DEGRADED)
            and c.circuit_state != CircuitState.OPEN
        ]

        if not eligible_candidates:
            # Fallback to all candidates if none explicitly marked eligible
            eligible_candidates = list(candidates)

        if not eligible_candidates:
            # Explicit no-route when candidate pool is completely empty
            assignments: dict[str, TaskAssignment] = {
                t.task_id: TaskAssignment(
                    task_id=t.task_id, selected_agent_type=None, fallback_order=[]
                )
                for t in tasks
            }
            return TeamAssignment(assignments=assignments, selected_agent_ids=[])

        assignments = {}
        assigned_agents: set[str] = set()
        available_pool = list(eligible_candidates)
        used_agents: set[str] = set()

        for task in tasks:
            req = RoutingRequest(
                task_type=task.task_type,
                required_capabilities=task.required_capabilities,
            )

            # Prefer agents not yet assigned to an active task in this wave if task is parallel_safe
            pool_for_task = [
                c for c in available_pool
                if c.descriptor.agent_type not in used_agents
            ] if (task.parallel_safe and len(available_pool) > 1) else available_pool

            if not pool_for_task:
                pool_for_task = available_pool

            decision = self.router.route(req, pool_for_task)
            selected = decision.selected_agent_type

            assignments[task.task_id] = TaskAssignment(
                task_id=task.task_id,
                selected_agent_type=selected,
                fallback_order=list(decision.fallback_order),
            )
            if selected is not None:
                assigned_agents.add(selected)
                if task.parallel_safe:
                    used_agents.add(selected)

        return TeamAssignment(
            assignments=assignments,
            selected_agent_ids=sorted(list(assigned_agents)),
        )


__all__ = ["AgentOrganizationCompiler", "TaskAssignment", "TeamAssignment"]
