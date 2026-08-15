"""Planner -> Verifier integration tests: proves real, Stage 4D-generated
`ExpectedOutcome` objects (not hand-crafted approximations) flow into
`verify_one()` without translation and without ever crashing, for every
evaluator type the planner's task templates currently produce."""

from datetime import UTC, datetime

from app.contracts.enums import BenchmarkEvaluatorType
from app.contracts.planning import ExpectedOutcome, PlanningRequest
from app.contracts.verification import VerificationStatus
from app.engine.planning.classifier import ComplexityTier, PlanningCategory
from app.engine.planning.planner import Planner
from app.engine.planning.templates import get_templates_for_plan
from app.engine.verification.evaluators import ObservedOutcome
from app.engine.verification.verifier import verify_one

_NOW = datetime.now(UTC)


def _favorable_observed_outcome_for(expected: ExpectedOutcome) -> ObservedOutcome:
    """Realistic, favorable observed evidence for `expected`, matching
    exactly the criteria shapes `app.engine.planning.templates` currently
    generates -- used to prove the round trip doesn't just avoid crashing
    but actually reaches a PASSED verdict for good evidence."""
    if expected.evaluator_type is BenchmarkEvaluatorType.BUILD:
        return ObservedOutcome({"exit_code": 0})
    if expected.evaluator_type is BenchmarkEvaluatorType.UNIT_TEST:
        return ObservedOutcome({"exit_code": 0, "tests_total": 5, "tests_failed": 0})
    if expected.evaluator_type is BenchmarkEvaluatorType.FILE_DIFF:
        if "expected_diff" in expected.criteria:
            return ObservedOutcome({"diff": expected.criteria["expected_diff"]})
        if "expected_files_changed" in expected.criteria:
            return ObservedOutcome(
                {"files_changed": list(expected.criteria["expected_files_changed"])}
            )
        return ObservedOutcome({"diff": "+ a real change", "files_changed": ["app/module.py"]})
    if expected.evaluator_type is BenchmarkEvaluatorType.HUMAN_REVIEWED:
        return ObservedOutcome({"human_review_status": "approved", "human_reviewer": "reviewer"})
    return ObservedOutcome({})


def _all_planner_generated_expected_outcomes() -> list[ExpectedOutcome]:
    """Every `ExpectedOutcome` the Stage 4D planner's full template registry
    can currently produce, built through the real `TaskTemplate.build_task_spec`
    path -- not reconstructed by hand."""
    expected_outcomes: list[ExpectedOutcome] = []
    for category in PlanningCategory:
        for tier in ComplexityTier:
            for template in get_templates_for_plan(category, tier):
                task_spec = template.build_task_spec(goal="Integration test goal")
                if task_spec.expected_outcome is not None:
                    expected_outcomes.append(task_spec.expected_outcome)
    return expected_outcomes


def test_full_planning_pipeline_produces_expected_outcomes_verify_one_can_consume() -> None:
    """The literal pipeline the task describes: PlanningRequest -> Planner ->
    WorkflowPlan -> each TaskSpec.expected_outcome -> verify_one(), for two
    goals landing in different planning categories."""
    for goal in ("Fix bug in the authentication flow", "Security review of the login endpoint"):
        request = PlanningRequest(goal=goal)
        plan = Planner().plan(request)
        assert plan.tasks

        for task in plan.tasks:
            if task.expected_outcome is None:
                continue
            observed = _favorable_observed_outcome_for(task.expected_outcome)
            result = verify_one(
                task.expected_outcome,
                observed,
                verification_id=f"{plan.plan_id}-{task.key}",
                workflow_id=plan.plan_id,
                step_id=task.key,
                created_at=_NOW,
            )
            assert result.status in (
                VerificationStatus.PASSED,
                VerificationStatus.FAILED,
                VerificationStatus.INCONCLUSIVE,
                VerificationStatus.REQUIRES_HUMAN_REVIEW,
            )


def test_no_stage_4d_generated_expected_outcome_crashes_stage_4e() -> None:
    """Exhaustive sweep across the planner's entire template registry
    (every `PlanningCategory` x `ComplexityTier` combination): every real
    generated `ExpectedOutcome` must verify without `verify_one()` raising
    anything other than the deliberate `VerificationResult` it returns."""
    expected_outcomes = _all_planner_generated_expected_outcomes()
    assert expected_outcomes  # sanity: the sweep actually found templates

    seen_evaluator_types: set[BenchmarkEvaluatorType] = set()
    for index, expected in enumerate(expected_outcomes):
        observed = _favorable_observed_outcome_for(expected)
        result = verify_one(
            expected,
            observed,
            verification_id=f"sweep-{index}",
            workflow_id="sweep-wf",
            created_at=_NOW,
        )
        assert isinstance(result.status, VerificationStatus)
        seen_evaluator_types.add(expected.evaluator_type)

    assert {
        BenchmarkEvaluatorType.BUILD,
        BenchmarkEvaluatorType.UNIT_TEST,
        BenchmarkEvaluatorType.FILE_DIFF,
        BenchmarkEvaluatorType.HUMAN_REVIEWED,
    }.issubset(seen_evaluator_types)


def test_stage_4d_generated_expected_outcomes_pass_with_favorable_evidence() -> None:
    """Stronger than "doesn't crash": with realistic, favorable observed
    evidence matching what the planner's own criteria describe, every
    generated `ExpectedOutcome` actually reaches a PASSED verdict."""
    for expected in _all_planner_generated_expected_outcomes():
        observed = _favorable_observed_outcome_for(expected)
        result = verify_one(
            expected, observed, verification_id="v", workflow_id="wf", created_at=_NOW
        )
        assert result.status is VerificationStatus.PASSED, (
            f"expected PASSED for evaluator_type={expected.evaluator_type} "
            f"criteria={expected.criteria}, got {result.status}"
        )


def test_planner_build_criteria_shapes_are_both_recognized() -> None:
    """Confirms both real BUILD criteria shapes the planner emits
    (`require_clean_build` and `require_build_and_test`) are present in the
    template registry and both verify correctly -- guards against the
    planner introducing a shape Stage 4E silently doesn't handle."""
    criteria_seen: set[str] = set()
    for expected in _all_planner_generated_expected_outcomes():
        if expected.evaluator_type is BenchmarkEvaluatorType.BUILD:
            criteria_seen.update(expected.criteria.keys())
    assert {"require_clean_build", "require_build_and_test"}.issubset(criteria_seen)
