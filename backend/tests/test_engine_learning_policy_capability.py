"""Tests for `app.engine.learning.policy`'s capability-evidence handling:
supporting evidence only, never a hierarchy tier of its own, and never a
substitute for the Router's own hard required-capability check."""

import inspect
from datetime import UTC, datetime

from app.contracts.enums import AgentCapability, AgentExecutionStatus
from app.contracts.verification import VerificationStatus
from app.engine.learning.events import LearningEvent
from app.engine.learning.passport import rebuild_all_passports
from app.engine.learning.policy import LearningPolicy
from app.engine.learning.recommendation import (
    CAPABILITY_VERIFIED_HISTORY,
    AgentRecommendation,
    LearningRecommendation,
)

_NOW = datetime.now(UTC)


def _events(
    agent_type: str,
    n: int,
    *,
    prefix: str,
    verification_status: VerificationStatus | None,
    task_type: str | None = "code_generation",
    capabilities: tuple[AgentCapability, ...] = (),
) -> list[LearningEvent]:
    return [
        LearningEvent(
            event_id=f"{prefix}-{i}",
            workflow_id=f"wf-{prefix}-{i}",
            agent_type=agent_type,
            execution_status=AgentExecutionStatus.SUCCEEDED,
            created_at=_NOW,
            task_type=task_type,
            capabilities=capabilities,
            verification_status=verification_status,
        )
        for i in range(n)
    ]


def _recommend(events: list[LearningEvent], **kwargs: object) -> LearningRecommendation:
    passports = rebuild_all_passports(events, updated_at=_NOW)
    return LearningPolicy().recommend(passports, **kwargs)  # type: ignore[arg-type]


def test_capability_bucket_supports_and_boosts_recommendation() -> None:
    """Two agents with identical task-type evidence; only one also has
    strong, sufficiently-sampled evidence for the requested capability.
    That agent must score higher and carry the capability reason code."""
    shared_task_evidence_a = _events(
        "agent_with_capability", 8, prefix="a-task", verification_status=VerificationStatus.PASSED
    )
    capability_evidence = _events(
        "agent_with_capability",
        8,
        prefix="a-cap",
        verification_status=VerificationStatus.PASSED,
        task_type=None,
        capabilities=(AgentCapability.CODE_REVIEW,),
    )
    shared_task_evidence_b = _events(
        "agent_without_capability",
        8,
        prefix="b-task",
        verification_status=VerificationStatus.PASSED,
    )
    rec = _recommend(
        shared_task_evidence_a + capability_evidence + shared_task_evidence_b,
        task_type="code_generation",
        capability=AgentCapability.CODE_REVIEW,
    )
    by_agent = {r.agent_type: r for r in rec.agent_recommendations}
    with_capability = by_agent["agent_with_capability"]
    without_capability = by_agent["agent_without_capability"]
    assert CAPABILITY_VERIFIED_HISTORY in with_capability.reason_codes
    assert CAPABILITY_VERIFIED_HISTORY not in without_capability.reason_codes
    assert with_capability.score is not None
    assert without_capability.score is not None
    assert with_capability.score > without_capability.score


def test_missing_capability_evidence_is_neutral_not_penalized() -> None:
    """Requesting a capability with zero observed evidence for an agent
    must score identically to not requesting a capability at all."""
    events = _events("agent_a", 8, prefix="a", verification_status=VerificationStatus.PASSED)
    without_capability_request = _recommend(events, task_type="code_generation")
    with_unobserved_capability = _recommend(
        events, task_type="code_generation", capability=AgentCapability.DEBUGGING
    )
    assert (
        without_capability_request.agent_recommendations[0].score
        == with_unobserved_capability.agent_recommendations[0].score
    )


def test_capability_evidence_is_never_its_own_hierarchy_tier() -> None:
    """Capability-tagged events still count as real overall execution/
    verification history (a capability-only event set legitimately falls
    back to a real `overall` recommendation) -- but `tier_used` must never
    be `"capability"` itself: capability evidence only ever *supports* the
    score of whichever real hierarchy tier was selected, never stands in
    as a tier of its own."""
    capability_only_evidence = _events(
        "agent_a",
        20,
        prefix="cap",
        verification_status=VerificationStatus.PASSED,
        task_type=None,
        capabilities=(AgentCapability.CODE_REVIEW,),
    )
    rec = _recommend(
        capability_only_evidence,
        task_type="code_generation",
        capability=AgentCapability.CODE_REVIEW,
    )
    result = rec.agent_recommendations[0]
    assert result.tier_used != "capability"
    assert result.tier_used == "overall"


def test_capability_learning_never_bypasses_router_required_capability_checks() -> None:
    """Structural guard: `AgentRecommendation`/`policy.py` have no concept
    of capability *eligibility* at all -- no field claims an agent
    "satisfies" a required capability, and the module never imports the
    Router's own eligibility/constraint machinery."""
    field_names = {f.name for f in AgentRecommendation.__dataclass_fields__.values()}
    forbidden_substrings = ("eligible", "eligibility", "required_capabilit", "satisfies")
    for field_name in field_names:
        lowered = field_name.lower()
        assert not any(bad in lowered for bad in forbidden_substrings), field_name

    import app.engine.learning.policy as policy_module

    assert not hasattr(policy_module, "eligibility_violation")
    assert not hasattr(policy_module, "RoutingConstraints")
    import_lines = [
        line
        for line in inspect.getsource(policy_module).splitlines()
        if line.startswith(("import ", "from "))
    ]
    assert not any("routing.scorer" in line or "routing.router" in line for line in import_lines)
