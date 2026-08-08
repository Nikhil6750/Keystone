"""Rule-based task classification: mapping a free-text task description to
a `task_type` string the router can score candidates against.

Deliberately keyword-based, not model-based — a routing decision must stay
explainable and reproducible from its inputs alone; calling an external
model just to categorize a task would make classification itself opaque and
non-deterministic.
"""

from typing import Protocol

_KEYWORD_TASK_TYPES: tuple[tuple[str, str], ...] = (
    ("test", "test_generation"),
    ("debug", "debugging"),
    ("fix", "debugging"),
    ("refactor", "refactoring"),
    ("review", "code_review"),
    ("document", "documentation"),
    ("plan", "planning"),
)
DEFAULT_TASK_TYPE = "code_generation"


class TaskClassifier(Protocol):
    def classify(self, description: str) -> str: ...


class RuleBasedTaskClassifier:
    """Deterministic keyword-matching classifier.

    Checked in declaration order; the first matching keyword wins.
    Descriptions matching no keyword fall back to `DEFAULT_TASK_TYPE`.
    """

    def classify(self, description: str) -> str:
        lowered = description.lower()
        for keyword, task_type in _KEYWORD_TASK_TYPES:
            if keyword in lowered:
                return task_type
        return DEFAULT_TASK_TYPE


__all__ = ["DEFAULT_TASK_TYPE", "RuleBasedTaskClassifier", "TaskClassifier"]
