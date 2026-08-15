"""Tests for app.engine.planning.classifier."""

import pytest

from app.engine.planning.classifier import ComplexityTier, PlanningCategory, TaskClassifier


@pytest.fixture
def classifier() -> TaskClassifier:
    return TaskClassifier()


def test_normalization(classifier: TaskClassifier) -> None:
    assert classifier.normalize_goal("  Build  Authentication!  ") == "build authentication"
    assert (
        classifier.normalize_goal("Fix bug #1234: NullPointerException in User.py")
        == "fix bug 1234 nullpointerexception in user py"
    )


def test_category_classification_feature(classifier: TaskClassifier) -> None:
    res = classifier.classify("Build authentication for this repository")
    assert res.category == PlanningCategory.FEATURE_IMPLEMENTATION
    assert any("category_match:feature_implementation" in r for r in res.rule_identifiers)


def test_category_classification_bug_fix(classifier: TaskClassifier) -> None:
    res = classifier.classify("Fix issue where user login crashes on null email")
    assert res.category == PlanningCategory.BUG_FIX


def test_category_classification_refactor(classifier: TaskClassifier) -> None:
    res = classifier.classify("Refactor database adapter to simplify design")
    assert res.category == PlanningCategory.REFACTOR


def test_category_classification_test_creation(classifier: TaskClassifier) -> None:
    res = classifier.classify("Write pytest unit tests for authentication service")
    assert res.category == PlanningCategory.TEST_CREATION


def test_category_classification_documentation(classifier: TaskClassifier) -> None:
    res = classifier.classify("Update README docs with API usage guide")
    assert res.category == PlanningCategory.DOCUMENTATION


def test_category_classification_code_review(classifier: TaskClassifier) -> None:
    res = classifier.classify("Review code changes in pull request 42")
    assert res.category == PlanningCategory.CODE_REVIEW


def test_category_classification_security_review(classifier: TaskClassifier) -> None:
    res = classifier.classify("Perform security review and audit authentication surface")
    assert res.category == PlanningCategory.SECURITY_REVIEW


def test_category_classification_performance(classifier: TaskClassifier) -> None:
    res = classifier.classify("Optimize query latency and profiling throughput")
    assert res.category == PlanningCategory.PERFORMANCE_WORK


def test_category_classification_repo_analysis(classifier: TaskClassifier) -> None:
    res = classifier.classify("Analyze repository structure and map codebase dependencies")
    assert res.category == PlanningCategory.REPOSITORY_ANALYSIS


def test_category_classification_generic_fallback(classifier: TaskClassifier) -> None:
    res = classifier.classify("Do some mysterious work on something")
    assert res.category == PlanningCategory.GENERIC_TASK
    assert "category_match:generic_task:fallback" in res.rule_identifiers


def test_complexity_tier_small(classifier: TaskClassifier) -> None:
    res = classifier.classify("fix typo in readme")
    assert res.complexity_tier == ComplexityTier.SMALL


def test_complexity_tier_medium(classifier: TaskClassifier) -> None:
    res = classifier.classify("implement user profile settings page")
    assert res.complexity_tier == ComplexityTier.MEDIUM


def test_complexity_tier_large(classifier: TaskClassifier) -> None:
    res = classifier.classify(
        "implement authentication including database, multi-service architecture, API, and tests"
    )
    assert res.complexity_tier == ComplexityTier.LARGE
