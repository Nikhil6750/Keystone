"""Tests for `app.engine.learning.policy`'s evidence hierarchy: repository +
task-type evidence wins when sufficiently sampled; task-type, repository,
and overall evidence are each tried in turn as fallbacks; a narrow,
thinly-sampled bucket never overrides a broader, well-sampled one."""

from datetime import UTC, datetime

from app.contracts.enums import AgentExecutionStatus
from app.contracts.verification import VerificationStatus
from app.engine.learning.events import LearningEvent
from app.engine.learning.passport import rebuild_all_passports
from app.engine.learning.policy import LearningPolicy
from app.engine.learning.recommendation import AgentRecommendation

_NOW = datetime.now(UTC)
_AGENT = "claude_code"


def _events(
    n: int,
    *,
    prefix: str,
    verification_status: VerificationStatus | None,
    task_type: str | None,
    repository_id: str | None,
) -> list[LearningEvent]:
    return [
        LearningEvent(
            event_id=f"{prefix}-{i}",
            workflow_id=f"wf-{prefix}-{i}",
            agent_type=_AGENT,
            execution_status=AgentExecutionStatus.SUCCEEDED,
            created_at=_NOW,
            task_type=task_type,
            repository_id=repository_id,
            verification_status=verification_status,
        )
        for i in range(n)
    ]


def _recommend_one(events: list[LearningEvent], **kwargs: object) -> AgentRecommendation:
    passports = rebuild_all_passports(events, updated_at=_NOW)
    rec = LearningPolicy().recommend(passports, candidate_agent_types=[_AGENT], **kwargs)  # type: ignore[arg-type]
    return rec.agent_recommendations[0]


def test_repository_and_task_type_evidence_wins_when_sufficient() -> None:
    """Joint (repo, task) evidence is terrible; broader task-type-only
    evidence (different repository) is excellent. The joint tier still
    wins because it independently clears the sample threshold -- more
    specific evidence is preferred whenever it is trustworthy."""
    joint_bad = _events(
        8,
        prefix="joint",
        verification_status=VerificationStatus.FAILED,
        task_type="code_generation",
        repository_id="org/repo-a",
    )
    task_type_good_other_repo = _events(
        8,
        prefix="other",
        verification_status=VerificationStatus.PASSED,
        task_type="code_generation",
        repository_id="org/repo-b",
    )
    result = _recommend_one(
        joint_bad + task_type_good_other_repo,
        task_type="code_generation",
        repository_id="org/repo-a",
    )
    assert result.tier_used == "repository_task_type"
    assert result.verified_success_rate == 0.0


def test_task_type_fallback_when_no_joint_evidence() -> None:
    events = _events(
        8,
        prefix="t",
        verification_status=VerificationStatus.PASSED,
        task_type="code_generation",
        repository_id=None,
    )
    result = _recommend_one(events, task_type="code_generation", repository_id="org/unseen-repo")
    assert result.tier_used == "task_type"


def test_repository_fallback_when_no_joint_or_task_type_evidence() -> None:
    events = _events(
        8,
        prefix="r",
        verification_status=VerificationStatus.PASSED,
        task_type="code_review",
        repository_id="org/repo",
    )
    result = _recommend_one(events, task_type="code_generation", repository_id="org/repo")
    assert result.tier_used == "repository"


def test_overall_fallback_when_no_narrower_evidence_matches() -> None:
    events = _events(
        8,
        prefix="o",
        verification_status=VerificationStatus.PASSED,
        task_type="documentation",
        repository_id="org/other-repo",
    )
    result = _recommend_one(events, task_type="code_generation", repository_id="org/repo")
    assert result.tier_used == "overall"


def test_narrow_low_sample_bucket_does_not_override_strong_broader_evidence() -> None:
    """The joint (repo, task) bucket has only 2 verified samples with a
    terrible rate -- insufficient to trust. The broader task-type bucket
    has 20 additional verified samples with an excellent rate (the same 2
    narrow events legitimately also feed the broader task-type aggregate,
    since it groups by task_type alone -- that is correct, real
    aggregation, not a bug). The policy must select the broader tier
    (`task_type`), never the untrustworthy narrow one
    (`repository_task_type`), and the broader tier's rate must reflect the
    full, strong 20/22 evidence rather than the narrow 0/2 evidence alone."""
    joint_insufficient_and_bad = _events(
        2,
        prefix="joint",
        verification_status=VerificationStatus.FAILED,
        task_type="code_generation",
        repository_id="org/repo",
    )
    task_type_strong = _events(
        20,
        prefix="task",
        verification_status=VerificationStatus.PASSED,
        task_type="code_generation",
        repository_id=None,
    )
    result = _recommend_one(
        joint_insufficient_and_bad + task_type_strong,
        task_type="code_generation",
        repository_id="org/repo",
    )
    assert result.tier_used == "task_type"
    assert result.verified_sample_count == 22
    assert result.verified_success_rate == 20 / 22


def test_narrow_low_sample_repository_bucket_does_not_override_overall() -> None:
    """The repository bucket has only 1 verified sample with a terrible
    rate -- insufficient to trust. That single event also legitimately
    contributes to the overall aggregate (real aggregation, not a bug),
    diluting but not erasing the otherwise-excellent overall rate. The
    policy must select `overall`, never the untrustworthy `repository`
    tier."""
    repository_insufficient_and_bad = _events(
        1,
        prefix="repo",
        verification_status=VerificationStatus.FAILED,
        task_type="code_review",
        repository_id="org/repo",
    )
    overall_strong = _events(
        20,
        prefix="overall",
        verification_status=VerificationStatus.PASSED,
        task_type="documentation",
        repository_id=None,
    )
    result = _recommend_one(
        repository_insufficient_and_bad + overall_strong,
        task_type="code_generation",
        repository_id="org/repo",
    )
    assert result.tier_used == "overall"
    assert result.verified_sample_count == 21
    assert result.verified_success_rate == 20 / 21


def test_no_repository_requested_skips_repository_scoped_tiers() -> None:
    events = _events(
        8,
        prefix="t",
        verification_status=VerificationStatus.PASSED,
        task_type="code_generation",
        repository_id="org/repo",
    )
    result = _recommend_one(events, task_type="code_generation", repository_id=None)
    assert result.tier_used == "task_type"
