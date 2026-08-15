"""`ManagerOrchestrator`: the narrow coordinator between one `ManagerModel`
call and Keystone's existing, authoritative deterministic components.

```
User Goal
   |
   v
ManagerModel                     (this package, protocol.py)
   |
   v
Structured Manager Proposal      (models.py: ManagerResponse)
   |
   v
DETERMINISTIC KEYSTONE VALIDATION (validation.py: ManagerProposalValidator)
   |
   v
Planner                          (app.engine.planning.planner.Planner, unmodified, reused)
```

**What this class does, exactly:**

1. Invoke `ManagerModel.propose()` at most once, bounded by `timeout_seconds`.
2. Validate any returned `ManagerResponse` via `ManagerProposalValidator`.
3. Fold *only* the validated `preferred_agent_types` (never task counts,
   never verification/recovery authority, never anything else) into a
   `RoutingConstraints.preferred_agent_types` list on the `PlanningRequest`
   already supplied by the caller.
4. Call the existing `Planner.plan()` -- unmodified, exactly as Stage 4D
   built it -- to produce the one authoritative `WorkflowPlan`.

**What this class never does:** it never constructs a `WorkflowPlan`
itself, never calls `Router`, `WorkflowEngine`, a verification evaluator, or
a learning aggregator. `preferred_agent_types` is `Router`'s own documented
*non-eligibility-affecting* ranking signal (`app.engine.routing.scorer
._preference_score`) -- folding a manager's validated preference into it
can change *which eligible candidate ranks first*, never *whether* a
candidate is eligible at all. There is no per-task routing/compiler step in
this codebase yet (see `docs/contracts.md`'s "Execution interface
architecture"), so this orchestrator does not attempt to build one; that is
explicitly out of scope for Stage 8A.

**No retry loop.** `propose()` is called exactly once per `orchestrate()`
call, wrapped in one `asyncio.wait_for`. A timeout or any `ManagerError`
subclass is treated identically to "no manager configured": deterministic
fallback, `fallback_used=True`, and `Planner.plan()` still runs against the
caller's original (unmodified) `PlanningRequest`. Keystone is never
unusable because a manager model is slow, down, or misconfigured.
"""

import asyncio
from dataclasses import dataclass

from app.contracts.planning import PlanningRequest, WorkflowPlan
from app.engine.manager.errors import ManagerError
from app.engine.manager.models import ManagerRequest
from app.engine.manager.protocol import ManagerModel
from app.engine.manager.validation import ManagerProposalValidator
from app.engine.planning.planner import Planner

_DEFAULT_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class ManagerOrchestrationPolicy:
    """Bounds for one `ManagerOrchestrator.orchestrate()` call."""

    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


@dataclass(frozen=True)
class ManagerOrchestrationResult:
    """Observable outcome of one orchestration pass -- Keystone's own
    observable evidence only, never a prompt or chain-of-thought (Stage 8A
    rule 6). `selected_task_count` always reflects `plan.tasks` (the
    deterministic `Planner` output), never the manager's raw, unvalidated
    task-proposal count.
    """

    plan: WorkflowPlan
    manager_used: bool
    fallback_used: bool
    proposal_validated: bool
    selected_task_count: int
    warnings: tuple[str, ...] = ()
    manager_identifier: str | None = None
    evidence_references: tuple[str, ...] = ()
    validation_issue_codes: tuple[str, ...] = ()


def _merge_preferred_agent_types(
    planning_request: PlanningRequest, preferred_agent_types: list[str]
) -> PlanningRequest:
    """Return a new `PlanningRequest` whose `constraints.preferred_agent_types`
    is the union of the caller's original preferences and the manager's
    validated ones (deduplicated, sorted for determinism). Every other field
    -- crucially `constraints.excluded_agent_types` and every hard
    eligibility constraint -- is untouched, so this can never grant a
    manager-preferred candidate eligibility it did not already have."""
    if not preferred_agent_types:
        return planning_request
    merged = sorted(
        set(planning_request.constraints.preferred_agent_types) | set(preferred_agent_types)
    )
    new_constraints = planning_request.constraints.model_copy(
        update={"preferred_agent_types": merged}
    )
    return planning_request.model_copy(update={"constraints": new_constraints})


class ManagerOrchestrator:
    """Coordinates one `ManagerModel` call, deterministic validation, and
    the existing `Planner` -- see module docstring."""

    def __init__(
        self,
        *,
        manager_model: ManagerModel | None,
        planner: Planner | None = None,
        validator: ManagerProposalValidator | None = None,
        policy: ManagerOrchestrationPolicy | None = None,
    ) -> None:
        self._manager_model = manager_model
        self._planner = planner or Planner()
        self._validator = validator or ManagerProposalValidator()
        self._policy = policy or ManagerOrchestrationPolicy()

    async def orchestrate(
        self,
        *,
        planning_request: PlanningRequest,
        manager_request: ManagerRequest,
    ) -> ManagerOrchestrationResult:
        """Run one bounded manager-assisted planning pass.

        `manager_request` and `planning_request` are supplied by the caller
        (typically built together from the same goal/context -- see
        `context.py` for `manager_request`) rather than derived from one
        another here, so this method has no hidden coupling to how either
        was assembled.
        """
        warnings: list[str] = []
        manager_used = False
        proposal_validated = False
        manager_identifier: str | None = None
        evidence_references: list[str] = []
        validation_issue_codes: list[str] = []
        effective_planning_request = planning_request

        response = None
        if self._manager_model is None:
            warnings.append("no manager model configured; using deterministic fallback")
        else:
            manager_used = True
            try:
                response = await asyncio.wait_for(
                    self._manager_model.propose(manager_request),
                    timeout=self._policy.timeout_seconds,
                )
            except TimeoutError:
                warnings.append(
                    f"manager model timed out after {self._policy.timeout_seconds}s; "
                    "using deterministic fallback"
                )
            except ManagerError as exc:
                warnings.append(
                    f"manager model failed ({type(exc).__name__}); using deterministic fallback"
                )

        if response is not None:
            result = self._validator.validate(response, manager_request)
            proposal_validated = result.accepted
            if not result.accepted:
                validation_issue_codes = [issue.code for issue in result.issues]
                warnings.append(
                    "manager proposal rejected by deterministic validation; using unmodified plan"
                )
            else:
                manager_identifier = response.provider_identifier
                evidence_references = [item.kind for item in response.evidence_summary]
                warnings.extend(response.warnings)
                preferred = sorted(
                    {
                        agent_type
                        for task in response.task_proposals
                        for agent_type in task.preferred_agent_types
                    }
                )
                effective_planning_request = _merge_preferred_agent_types(
                    planning_request, preferred
                )

        fallback_used = not proposal_validated

        plan = self._planner.plan(effective_planning_request)

        return ManagerOrchestrationResult(
            plan=plan,
            manager_used=manager_used,
            fallback_used=fallback_used,
            proposal_validated=proposal_validated,
            selected_task_count=len(plan.tasks),
            warnings=tuple(warnings),
            manager_identifier=manager_identifier,
            evidence_references=tuple(evidence_references),
            validation_issue_codes=tuple(validation_issue_codes),
        )


__all__ = ["ManagerOrchestrationPolicy", "ManagerOrchestrationResult", "ManagerOrchestrator"]
