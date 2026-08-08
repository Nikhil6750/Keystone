"""Tests for app.engine.planning.templates."""

from app.contracts.enums import AgentCapability, BenchmarkEvaluatorType
from app.engine.planning.classifier import ComplexityTier, PlanningCategory
from app.engine.planning.templates import get_templates_for_plan


def test_feature_implementation_medium_template() -> None:
    templates = get_templates_for_plan(
        PlanningCategory.FEATURE_IMPLEMENTATION, ComplexityTier.MEDIUM
    )
    keys = [t.key for t in templates]
    assert keys == [
        "analyze_repository",
        "design_solution",
        "implement_change",
        "write_tests",
        "review_change",
        "validate_result",
    ]

    # Verify capability mapping
    impl_tmpl = next(t for t in templates if t.key == "implement_change")
    assert AgentCapability.CODE_GENERATION in impl_tmpl.required_capabilities

    # Verify objective expected outcome
    assert impl_tmpl.expected_outcome is not None
    assert impl_tmpl.expected_outcome.evaluator_type == BenchmarkEvaluatorType.BUILD


def test_feature_implementation_large_parallel_branch() -> None:
    templates = get_templates_for_plan(
        PlanningCategory.FEATURE_IMPLEMENTATION, ComplexityTier.LARGE
    )
    task_map = {t.key: t for t in templates}
    assert "write_tests" in task_map
    assert "documentation_update" in task_map
    assert task_map["write_tests"].depends_on == ["implement_change"]
    assert task_map["documentation_update"].depends_on == ["implement_change"]
    assert task_map["final_validation"].depends_on == [
        "security_review",
        "documentation_update",
    ]


def test_bug_fix_template() -> None:
    templates = get_templates_for_plan(PlanningCategory.BUG_FIX, ComplexityTier.MEDIUM)
    keys = [t.key for t in templates]
    assert keys == [
        "reproduce_issue",
        "analyze_root_cause",
        "implement_fix",
        "regression_tests",
        "final_validation",
    ]


def test_code_review_template() -> None:
    templates = get_templates_for_plan(PlanningCategory.CODE_REVIEW, ComplexityTier.MEDIUM)
    keys = [t.key for t in templates]
    assert keys == [
        "analyze_changes",
        "correctness_review",
        "security_review",
        "summarize_findings",
    ]


def test_refactor_template() -> None:
    templates = get_templates_for_plan(PlanningCategory.REFACTOR, ComplexityTier.MEDIUM)
    keys = [t.key for t in templates]
    assert keys == [
        "analyze_current_design",
        "define_refactor_boundary",
        "implement_refactor",
        "regression_tests",
        "validate_behavior",
    ]
