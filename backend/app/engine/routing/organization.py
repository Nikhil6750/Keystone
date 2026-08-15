"""Agent Organization Compiler.

Assembles execution teams dynamically by mapping compiled tasks to candidate agents.
Selects effective teams (e.g. 1 agent for sequential graphs, distinct agents for parallel tasks).
Does NOT use hardcoded provider rules; respects eligibility hard filters and router scoring.
"""

from typing import Any

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

    def __init__(
        self,
        router: Router | None = None,
        skill_agent_intelligence: Any | None = None,
    ) -> None:
        self.router = router or Router()
        self.skill_agent_intelligence = skill_agent_intelligence

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
            c
            for c in candidates
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
            pool_for_task = (
                [c for c in available_pool if c.descriptor.agent_type not in used_agents]
                if (task.parallel_safe and len(available_pool) > 1)
                else available_pool
            )

            if not pool_for_task:
                pool_for_task = available_pool

            decision = self.router.route(req, pool_for_task)
            selected = decision.selected_agent_type
            fallback_order = list(decision.fallback_order)

            # Skill × Agent Signal Integration:
            # When a task has an assigned skill, adjust candidate scores using empirical evidence.
            skill_id = getattr(task, "skill_id", None)
            if skill_id and self.skill_agent_intelligence is not None and decision.candidates:
                # Rank candidates with bounded skill-agent adjustment
                adjusted_candidates: list[tuple[float, int, str]] = []
                for score_record in decision.candidates:
                    if not score_record.eligible:
                        continue
                    agent_type = score_record.agent_type
                    perf = self.skill_agent_intelligence.get_agent_skill_performance(
                        skill_id, agent_type
                    )
                    # Minimum sample threshold of 2 runs required before adjustment applies
                    if perf.total_runs >= 2:
                        raw_adj = (perf.empirical_score() - 0.5) * 0.3
                        adj = max(-0.15, min(0.15, raw_adj))
                    else:
                        adj = 0.0

                    base_score = (
                        score_record.composite_score
                        if score_record.composite_score is not None
                        else 0.0
                    )
                    final_score = base_score + adj
                    sample_size = getattr(score_record, "sample_size", 0)
                    adjusted_candidates.append((final_score, sample_size, agent_type))

                if adjusted_candidates:
                    # Sort descending by adjusted score, then sample size, then agent_type
                    adjusted_candidates.sort(key=lambda x: (-x[0], -x[1], x[2]))
                    selected = adjusted_candidates[0][2]
                    fallback_order = [c[2] for c in adjusted_candidates[1:]]

            assignments[task.task_id] = TaskAssignment(
                task_id=task.task_id,
                selected_agent_type=selected,
                fallback_order=fallback_order,
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
