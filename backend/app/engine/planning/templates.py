"""Task template definitions for Stage 4D Workflow Planner.

Provides deterministic DAG templates mapping (PlanningCategory, ComplexityTier) to ordered
TaskSpec models with provider-neutral capabilities and objective expected outcomes.
"""

from typing import Any

from app.contracts.enums import AgentCapability, BenchmarkEvaluatorType
from app.contracts.planning import ExpectedOutcome, TaskSpec
from app.engine.planning.classifier import ComplexityTier, PlanningCategory


class TaskTemplate:
    """Blueprint for creating deterministic TaskSpecs."""

    def __init__(
        self,
        key: str,
        name: str,
        task_type: str,
        required_capabilities: list[AgentCapability],
        depends_on: list[str] | None = None,
        expected_outcome: ExpectedOutcome | None = None,
        input_payload_extra: dict[str, Any] | None = None,
    ) -> None:
        self.key = key
        self.name = name
        self.task_type = task_type
        self.required_capabilities = required_capabilities
        self.depends_on = depends_on or []
        self.expected_outcome = expected_outcome
        self.input_payload_extra = input_payload_extra or {}

    def build_task_spec(self, goal: str, context: dict[str, Any] | None = None) -> TaskSpec:
        """Instantiate a provider-neutral TaskSpec for a specific goal."""
        payload: dict[str, Any] = {"objective": self.name, "goal": goal}
        if self.input_payload_extra:
            payload.update(self.input_payload_extra)
        if context:
            payload.update(context)

        return TaskSpec(
            key=self.key,
            name=self.name,
            task_type=self.task_type,
            required_capabilities=list(self.required_capabilities),
            depends_on=list(self.depends_on),
            input_payload=payload,
            expected_outcome=self.expected_outcome,
        )


# Category and complexity to template registry mapping
_TEMPLATE_REGISTRY: dict[tuple[PlanningCategory, ComplexityTier], list[TaskTemplate]] = {}


def _register(
    category: PlanningCategory,
    tiers: list[ComplexityTier],
    templates: list[TaskTemplate],
) -> None:
    for tier in tiers:
        _TEMPLATE_REGISTRY[(category, tier)] = templates


# 1. FEATURE IMPLEMENTATION
_register(
    PlanningCategory.FEATURE_IMPLEMENTATION,
    [ComplexityTier.SMALL],
    [
        TaskTemplate(
            key="implement_change",
            name="Implement feature change",
            task_type="code_generation",
            required_capabilities=[AgentCapability.CODE_GENERATION],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.BUILD,
                criteria={"require_clean_build": True},
                description="Build succeeds cleanly",
            ),
        ),
        TaskTemplate(
            key="validate_result",
            name="Validate feature implementation",
            task_type="test_execution",
            required_capabilities=[AgentCapability.TEST_EXECUTION],
            depends_on=["implement_change"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.UNIT_TEST,
                criteria={"require_all_pass": True},
                description="Tests pass cleanly",
            ),
        ),
    ],
)

_register(
    PlanningCategory.FEATURE_IMPLEMENTATION,
    [ComplexityTier.MEDIUM],
    [
        TaskTemplate(
            key="analyze_repository",
            name="Analyze repository structure",
            task_type="repository_analysis",
            required_capabilities=[AgentCapability.GENERAL_REASONING],
        ),
        TaskTemplate(
            key="design_solution",
            name="Design solution architecture",
            task_type="planning",
            required_capabilities=[AgentCapability.PLANNING],
            depends_on=["analyze_repository"],
        ),
        TaskTemplate(
            key="implement_change",
            name="Implement feature code",
            task_type="code_generation",
            required_capabilities=[AgentCapability.CODE_GENERATION],
            depends_on=["design_solution"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.BUILD,
                criteria={"require_clean_build": True},
                description="Build succeeds cleanly",
            ),
        ),
        TaskTemplate(
            key="write_tests",
            name="Write feature tests",
            task_type="test_generation",
            required_capabilities=[AgentCapability.TEST_GENERATION],
            depends_on=["implement_change"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.UNIT_TEST,
                criteria={"require_all_pass": True},
                description="Unit tests pass",
            ),
        ),
        TaskTemplate(
            key="review_change",
            name="Review code changes",
            task_type="code_review",
            required_capabilities=[AgentCapability.CODE_REVIEW],
            depends_on=["write_tests"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.FILE_DIFF,
                criteria={"require_non_empty_diff": True},
                description="Diff review complete",
            ),
        ),
        TaskTemplate(
            key="validate_result",
            name="Run final validation",
            task_type="test_execution",
            required_capabilities=[AgentCapability.TEST_EXECUTION],
            depends_on=["review_change"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.UNIT_TEST,
                criteria={"require_all_pass": True},
                description="Final test validation succeeds",
            ),
        ),
    ],
)

_register(
    PlanningCategory.FEATURE_IMPLEMENTATION,
    [ComplexityTier.LARGE],
    [
        TaskTemplate(
            key="analyze_repository",
            name="Analyze repository structure",
            task_type="repository_analysis",
            required_capabilities=[AgentCapability.GENERAL_REASONING],
        ),
        TaskTemplate(
            key="design_solution",
            name="Design solution architecture",
            task_type="planning",
            required_capabilities=[AgentCapability.PLANNING],
            depends_on=["analyze_repository"],
        ),
        TaskTemplate(
            key="implement_change",
            name="Implement feature code",
            task_type="code_generation",
            required_capabilities=[AgentCapability.CODE_GENERATION],
            depends_on=["design_solution"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.BUILD,
                criteria={"require_clean_build": True},
                description="Build succeeds cleanly",
            ),
        ),
        TaskTemplate(
            key="write_tests",
            name="Write automated tests",
            task_type="test_generation",
            required_capabilities=[AgentCapability.TEST_GENERATION],
            depends_on=["implement_change"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.UNIT_TEST,
                criteria={"require_all_pass": True},
                description="Unit tests pass",
            ),
        ),
        TaskTemplate(
            key="documentation_update",
            name="Update documentation",
            task_type="documentation",
            required_capabilities=[AgentCapability.DOCUMENTATION],
            depends_on=["implement_change"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.FILE_DIFF,
                criteria={"require_non_empty_diff": True},
                description="Documentation updated",
            ),
        ),
        TaskTemplate(
            key="security_review",
            name="Perform security review",
            task_type="code_review",
            required_capabilities=[AgentCapability.CODE_REVIEW],
            depends_on=["write_tests"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.FILE_DIFF,
                criteria={"require_non_empty_diff": True},
                description="Security review complete",
            ),
        ),
        TaskTemplate(
            key="final_validation",
            name="Run pipeline validation",
            task_type="test_execution",
            required_capabilities=[AgentCapability.TEST_EXECUTION],
            depends_on=["security_review", "documentation_update"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.BUILD,
                criteria={"require_build_and_test": True},
                description="Full validation succeeds",
            ),
        ),
    ],
)


# 2. BUG FIX
_register(
    PlanningCategory.BUG_FIX,
    [ComplexityTier.SMALL],
    [
        TaskTemplate(
            key="implement_fix",
            name="Apply bug fix",
            task_type="code_generation",
            required_capabilities=[AgentCapability.CODE_GENERATION],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.BUILD,
                criteria={"require_clean_build": True},
                description="Fix compiles cleanly",
            ),
        ),
        TaskTemplate(
            key="final_validation",
            name="Verify bug fix",
            task_type="test_execution",
            required_capabilities=[AgentCapability.TEST_EXECUTION],
            depends_on=["implement_fix"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.UNIT_TEST,
                criteria={"require_all_pass": True},
                description="Tests pass cleanly",
            ),
        ),
    ],
)

_register(
    PlanningCategory.BUG_FIX,
    [ComplexityTier.MEDIUM, ComplexityTier.LARGE],
    [
        TaskTemplate(
            key="reproduce_issue",
            name="Reproduce reported issue",
            task_type="debugging",
            required_capabilities=[AgentCapability.DEBUGGING],
        ),
        TaskTemplate(
            key="analyze_root_cause",
            name="Analyze root cause",
            task_type="general_reasoning",
            required_capabilities=[AgentCapability.GENERAL_REASONING],
            depends_on=["reproduce_issue"],
        ),
        TaskTemplate(
            key="implement_fix",
            name="Implement bug fix",
            task_type="code_generation",
            required_capabilities=[AgentCapability.CODE_GENERATION],
            depends_on=["analyze_root_cause"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.BUILD,
                criteria={"require_clean_build": True},
                description="Build succeeds cleanly",
            ),
        ),
        TaskTemplate(
            key="regression_tests",
            name="Add regression tests",
            task_type="test_generation",
            required_capabilities=[AgentCapability.TEST_GENERATION],
            depends_on=["implement_fix"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.UNIT_TEST,
                criteria={"require_all_pass": True},
                description="Regression tests pass",
            ),
        ),
        TaskTemplate(
            key="final_validation",
            name="Run final validation",
            task_type="test_execution",
            required_capabilities=[AgentCapability.TEST_EXECUTION],
            depends_on=["regression_tests"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.BUILD,
                criteria={"require_build_and_test": True},
                description="Final validation succeeds",
            ),
        ),
    ],
)


# 3. REFACTOR
_register(
    PlanningCategory.REFACTOR,
    [ComplexityTier.SMALL],
    [
        TaskTemplate(
            key="implement_refactor",
            name="Apply code refactor",
            task_type="refactoring",
            required_capabilities=[AgentCapability.REFACTORING],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.BUILD,
                criteria={"require_clean_build": True},
                description="Refactored build succeeds",
            ),
        ),
        TaskTemplate(
            key="validate_behavior",
            name="Validate refactored behavior",
            task_type="test_execution",
            required_capabilities=[AgentCapability.TEST_EXECUTION],
            depends_on=["implement_refactor"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.UNIT_TEST,
                criteria={"require_all_pass": True},
                description="Behavioral tests pass",
            ),
        ),
    ],
)

_register(
    PlanningCategory.REFACTOR,
    [ComplexityTier.MEDIUM, ComplexityTier.LARGE],
    [
        TaskTemplate(
            key="analyze_current_design",
            name="Analyze current design",
            task_type="general_reasoning",
            required_capabilities=[AgentCapability.GENERAL_REASONING],
        ),
        TaskTemplate(
            key="define_refactor_boundary",
            name="Define refactoring boundaries",
            task_type="planning",
            required_capabilities=[AgentCapability.PLANNING],
            depends_on=["analyze_current_design"],
        ),
        TaskTemplate(
            key="implement_refactor",
            name="Implement refactored code",
            task_type="refactoring",
            required_capabilities=[AgentCapability.REFACTORING],
            depends_on=["define_refactor_boundary"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.BUILD,
                criteria={"require_clean_build": True},
                description="Build succeeds cleanly",
            ),
        ),
        TaskTemplate(
            key="regression_tests",
            name="Run regression test suite",
            task_type="test_generation",
            required_capabilities=[AgentCapability.TEST_GENERATION],
            depends_on=["implement_refactor"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.UNIT_TEST,
                criteria={"require_all_pass": True},
                description="Regression tests pass",
            ),
        ),
        TaskTemplate(
            key="validate_behavior",
            name="Validate system behavior",
            task_type="test_execution",
            required_capabilities=[AgentCapability.TEST_EXECUTION],
            depends_on=["regression_tests"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.BUILD,
                criteria={"require_build_and_test": True},
                description="Full behavior validated",
            ),
        ),
    ],
)


# 4. CODE REVIEW
_register(
    PlanningCategory.CODE_REVIEW,
    [ComplexityTier.SMALL],
    [
        TaskTemplate(
            key="correctness_review",
            name="Review code correctness",
            task_type="code_review",
            required_capabilities=[AgentCapability.CODE_REVIEW],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.FILE_DIFF,
                criteria={"require_non_empty_diff": True},
                description="Review complete",
            ),
        ),
    ],
)

_register(
    PlanningCategory.CODE_REVIEW,
    [ComplexityTier.MEDIUM, ComplexityTier.LARGE],
    [
        TaskTemplate(
            key="analyze_changes",
            name="Analyze code changes",
            task_type="general_reasoning",
            required_capabilities=[AgentCapability.GENERAL_REASONING],
        ),
        TaskTemplate(
            key="correctness_review",
            name="Perform correctness review",
            task_type="code_review",
            required_capabilities=[AgentCapability.CODE_REVIEW],
            depends_on=["analyze_changes"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.FILE_DIFF,
                criteria={"require_non_empty_diff": True},
                description="Correctness review complete",
            ),
        ),
        TaskTemplate(
            key="security_review",
            name="Perform security review",
            task_type="code_review",
            required_capabilities=[AgentCapability.CODE_REVIEW],
            depends_on=["analyze_changes"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.FILE_DIFF,
                criteria={"require_non_empty_diff": True},
                description="Security review complete",
            ),
        ),
        TaskTemplate(
            key="summarize_findings",
            name="Summarize review findings",
            task_type="general_reasoning",
            required_capabilities=[AgentCapability.GENERAL_REASONING],
            depends_on=["correctness_review", "security_review"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.HUMAN_REVIEWED,
                description="Review findings summarized",
            ),
        ),
    ],
)


# 5. TEST CREATION
_register(
    PlanningCategory.TEST_CREATION,
    [ComplexityTier.SMALL],
    [
        TaskTemplate(
            key="write_tests",
            name="Write target unit tests",
            task_type="test_generation",
            required_capabilities=[AgentCapability.TEST_GENERATION],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.UNIT_TEST,
                criteria={"require_all_pass": True},
                description="Unit tests pass",
            ),
        ),
    ],
)

_register(
    PlanningCategory.TEST_CREATION,
    [ComplexityTier.MEDIUM, ComplexityTier.LARGE],
    [
        TaskTemplate(
            key="analyze_code_coverage",
            name="Analyze code coverage gaps",
            task_type="general_reasoning",
            required_capabilities=[AgentCapability.GENERAL_REASONING],
        ),
        TaskTemplate(
            key="write_tests",
            name="Write comprehensive test suite",
            task_type="test_generation",
            required_capabilities=[AgentCapability.TEST_GENERATION],
            depends_on=["analyze_code_coverage"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.UNIT_TEST,
                criteria={"require_all_pass": True},
                description="Unit tests written",
            ),
        ),
        TaskTemplate(
            key="execute_tests",
            name="Execute test suite",
            task_type="test_execution",
            required_capabilities=[AgentCapability.TEST_EXECUTION],
            depends_on=["write_tests"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.UNIT_TEST,
                criteria={"require_all_pass": True},
                description="All tests execute cleanly",
            ),
        ),
    ],
)


# 6. DOCUMENTATION
_register(
    PlanningCategory.DOCUMENTATION,
    [ComplexityTier.SMALL],
    [
        TaskTemplate(
            key="update_documentation",
            name="Update documentation content",
            task_type="documentation",
            required_capabilities=[AgentCapability.DOCUMENTATION],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.FILE_DIFF,
                criteria={"require_non_empty_diff": True},
                description="Documentation updated",
            ),
        ),
    ],
)

_register(
    PlanningCategory.DOCUMENTATION,
    [ComplexityTier.MEDIUM, ComplexityTier.LARGE],
    [
        TaskTemplate(
            key="analyze_docs",
            name="Analyze current documentation",
            task_type="general_reasoning",
            required_capabilities=[AgentCapability.GENERAL_REASONING],
        ),
        TaskTemplate(
            key="update_documentation",
            name="Update documentation files",
            task_type="documentation",
            required_capabilities=[AgentCapability.DOCUMENTATION],
            depends_on=["analyze_docs"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.FILE_DIFF,
                criteria={"require_non_empty_diff": True},
                description="Documentation written",
            ),
        ),
        TaskTemplate(
            key="review_documentation",
            name="Review documentation clarity",
            task_type="code_review",
            required_capabilities=[AgentCapability.CODE_REVIEW],
            depends_on=["update_documentation"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.HUMAN_REVIEWED,
                description="Docs reviewed",
            ),
        ),
    ],
)


# 7. SECURITY REVIEW
_register(
    PlanningCategory.SECURITY_REVIEW,
    [ComplexityTier.SMALL],
    [
        TaskTemplate(
            key="security_audit",
            name="Perform security audit",
            task_type="code_review",
            required_capabilities=[AgentCapability.CODE_REVIEW],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.FILE_DIFF,
                criteria={"require_non_empty_diff": True},
                description="Audit complete",
            ),
        ),
    ],
)

_register(
    PlanningCategory.SECURITY_REVIEW,
    [ComplexityTier.MEDIUM, ComplexityTier.LARGE],
    [
        TaskTemplate(
            key="analyze_security_surface",
            name="Analyze attack surface",
            task_type="general_reasoning",
            required_capabilities=[AgentCapability.GENERAL_REASONING],
        ),
        TaskTemplate(
            key="security_audit",
            name="Perform deep security audit",
            task_type="code_review",
            required_capabilities=[AgentCapability.CODE_REVIEW],
            depends_on=["analyze_security_surface"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.FILE_DIFF,
                criteria={"require_non_empty_diff": True},
                description="Audit completed",
            ),
        ),
        TaskTemplate(
            key="report_vulnerabilities",
            name="Report security vulnerabilities",
            task_type="general_reasoning",
            required_capabilities=[AgentCapability.GENERAL_REASONING],
            depends_on=["security_audit"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.HUMAN_REVIEWED,
                description="Security report generated",
            ),
        ),
    ],
)


# 8. PERFORMANCE WORK
_register(
    PlanningCategory.PERFORMANCE_WORK,
    [ComplexityTier.SMALL],
    [
        TaskTemplate(
            key="implement_optimization",
            name="Implement performance optimization",
            task_type="code_generation",
            required_capabilities=[AgentCapability.CODE_GENERATION],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.BUILD,
                criteria={"require_clean_build": True},
                description="Optimization compiles",
            ),
        ),
        TaskTemplate(
            key="validate_behavior",
            name="Verify behavior after optimization",
            task_type="test_execution",
            required_capabilities=[AgentCapability.TEST_EXECUTION],
            depends_on=["implement_optimization"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.UNIT_TEST,
                criteria={"require_all_pass": True},
                description="Tests pass cleanly",
            ),
        ),
    ],
)

_register(
    PlanningCategory.PERFORMANCE_WORK,
    [ComplexityTier.MEDIUM, ComplexityTier.LARGE],
    [
        TaskTemplate(
            key="profile_performance",
            name="Profile system performance",
            task_type="general_reasoning",
            required_capabilities=[AgentCapability.GENERAL_REASONING],
        ),
        TaskTemplate(
            key="analyze_bottlenecks",
            name="Analyze performance bottlenecks",
            task_type="general_reasoning",
            required_capabilities=[AgentCapability.GENERAL_REASONING],
            depends_on=["profile_performance"],
        ),
        TaskTemplate(
            key="implement_optimization",
            name="Implement performance fixes",
            task_type="code_generation",
            required_capabilities=[AgentCapability.CODE_GENERATION],
            depends_on=["analyze_bottlenecks"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.BUILD,
                criteria={"require_clean_build": True},
                description="Build succeeds cleanly",
            ),
        ),
        TaskTemplate(
            key="benchmark_performance",
            name="Benchmark performance gain",
            task_type="test_execution",
            required_capabilities=[AgentCapability.TEST_EXECUTION],
            depends_on=["implement_optimization"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.UNIT_TEST,
                criteria={"require_all_pass": True},
                description="Benchmarks pass",
            ),
        ),
        TaskTemplate(
            key="validate_behavior",
            name="Validate system regression suite",
            task_type="test_execution",
            required_capabilities=[AgentCapability.TEST_EXECUTION],
            depends_on=["benchmark_performance"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.BUILD,
                criteria={"require_build_and_test": True},
                description="Full regression suite succeeds",
            ),
        ),
    ],
)


# 9. REPOSITORY ANALYSIS
_register(
    PlanningCategory.REPOSITORY_ANALYSIS,
    [ComplexityTier.SMALL, ComplexityTier.MEDIUM, ComplexityTier.LARGE],
    [
        TaskTemplate(
            key="analyze_repository_structure",
            name="Analyze repository structure",
            task_type="repository_analysis",
            required_capabilities=[AgentCapability.GENERAL_REASONING],
        ),
        TaskTemplate(
            key="map_dependencies",
            name="Map codebase dependencies",
            task_type="general_reasoning",
            required_capabilities=[AgentCapability.GENERAL_REASONING],
            depends_on=["analyze_repository_structure"],
        ),
        TaskTemplate(
            key="summarize_architecture",
            name="Summarize repository architecture",
            task_type="documentation",
            required_capabilities=[AgentCapability.DOCUMENTATION],
            depends_on=["map_dependencies"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.HUMAN_REVIEWED,
                description="Architecture summary generated",
            ),
        ),
    ],
)


# 10. GENERIC TASK
_register(
    PlanningCategory.GENERIC_TASK,
    [ComplexityTier.SMALL],
    [
        TaskTemplate(
            key="execute_task",
            name="Execute requested task",
            task_type="general_reasoning",
            required_capabilities=[AgentCapability.GENERAL_REASONING],
        ),
    ],
)

_register(
    PlanningCategory.GENERIC_TASK,
    [ComplexityTier.MEDIUM, ComplexityTier.LARGE],
    [
        TaskTemplate(
            key="analyze_task",
            name="Analyze task requirements",
            task_type="general_reasoning",
            required_capabilities=[AgentCapability.GENERAL_REASONING],
        ),
        TaskTemplate(
            key="execute_task",
            name="Execute core task",
            task_type="code_generation",
            required_capabilities=[AgentCapability.CODE_GENERATION],
            depends_on=["analyze_task"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.BUILD,
                criteria={"require_clean_build": True},
                description="Task build succeeds",
            ),
        ),
        TaskTemplate(
            key="validate_result",
            name="Validate task result",
            task_type="test_execution",
            required_capabilities=[AgentCapability.TEST_EXECUTION],
            depends_on=["execute_task"],
            expected_outcome=ExpectedOutcome(
                evaluator_type=BenchmarkEvaluatorType.UNIT_TEST,
                criteria={"require_all_pass": True},
                description="Validation succeeds",
            ),
        ),
    ],
)


def get_templates_for_plan(
    category: PlanningCategory, complexity: ComplexityTier
) -> list[TaskTemplate]:
    """Retrieve deterministic task templates for a category and complexity tier."""
    key = (category, complexity)
    if key in _TEMPLATE_REGISTRY:
        return _TEMPLATE_REGISTRY[key]
    # Fallback to generic task
    return _TEMPLATE_REGISTRY.get(
        (PlanningCategory.GENERIC_TASK, complexity),
        _TEMPLATE_REGISTRY[(PlanningCategory.GENERIC_TASK, ComplexityTier.MEDIUM)],
    )


__all__ = ["TaskTemplate", "get_templates_for_plan"]
