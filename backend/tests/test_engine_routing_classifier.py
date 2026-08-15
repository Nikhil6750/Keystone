"""Tests for `RuleBasedTaskClassifier`."""

from app.engine.routing.classifier import DEFAULT_TASK_TYPE, RuleBasedTaskClassifier


def test_classifies_test_related_descriptions() -> None:
    classifier = RuleBasedTaskClassifier()
    assert classifier.classify("Write unit tests for the parser") == "test_generation"


def test_classifies_debugging_descriptions() -> None:
    classifier = RuleBasedTaskClassifier()
    assert classifier.classify("Debug the failing login flow") == "debugging"
    assert classifier.classify("Fix the null pointer exception") == "debugging"


def test_classification_is_case_insensitive() -> None:
    classifier = RuleBasedTaskClassifier()
    assert classifier.classify("REVIEW this pull request") == "code_review"


def test_unmatched_description_falls_back_to_default() -> None:
    classifier = RuleBasedTaskClassifier()
    assert classifier.classify("do the thing") == DEFAULT_TASK_TYPE


def test_classification_is_deterministic() -> None:
    classifier = RuleBasedTaskClassifier()
    description = "Refactor and document the auth module"
    first = classifier.classify(description)
    second = classifier.classify(description)
    assert first == second
