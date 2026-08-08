"""Deterministic intent and goal classifier for Stage 4D Workflow Planning.

Maps unstructured goal text to transparent planning categories and complexity tiers
using deterministic keyword rules, text normalization, and observable classification
provenance. Same input always yields the exact same classification.
"""

import re
from enum import StrEnum
from typing import NamedTuple


class PlanningCategory(StrEnum):
    """Supported deterministic planning categories."""

    FEATURE_IMPLEMENTATION = "feature_implementation"
    BUG_FIX = "bug_fix"
    REFACTOR = "refactor"
    TEST_CREATION = "test_creation"
    DOCUMENTATION = "documentation"
    CODE_REVIEW = "code_review"
    SECURITY_REVIEW = "security_review"
    PERFORMANCE_WORK = "performance_work"
    REPOSITORY_ANALYSIS = "repository_analysis"
    GENERIC_TASK = "generic_task"


class ComplexityTier(StrEnum):
    """Deterministic complexity tiers based on observable goal characteristics."""

    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class ClassificationResult(NamedTuple):
    """Output of goal classification with observable provenance rules."""

    category: PlanningCategory
    complexity_tier: ComplexityTier
    rule_identifiers: list[str]
    normalized_goal: str


class TaskClassifier:
    """Deterministic keyword- and rule-based classifier for software goals."""

    # Keyword rules ordered by specificity
    _CATEGORY_RULES: list[tuple[PlanningCategory, list[str]]] = [
        (
            PlanningCategory.SECURITY_REVIEW,
            [
                "security review",
                "security audit",
                "vulnerability",
                "cve",
                "threat model",
                "penetration",
                "auth sec",
            ],
        ),
        (
            PlanningCategory.CODE_REVIEW,
            [
                "code review",
                "pull request",
                "pr review",
                "diff review",
                "inspect code",
                "review change",
                "review",
            ],
        ),
        (
            PlanningCategory.BUG_FIX,
            [
                "bug fix",
                "fix bug",
                "fix issue",
                "reproduce issue",
                "error",
                "crash",
                "regression",
                "defect",
                "patch",
                "bug",
                "fix",
            ],
        ),
        (
            PlanningCategory.REFACTOR,
            [
                "refactor",
                "clean up",
                "restructure",
                "reorganize",
                "rewrite",
                "decouple",
                "simplify design",
            ],
        ),
        (
            PlanningCategory.TEST_CREATION,
            [
                "write tests",
                "create tests",
                "add tests",
                "unit test",
                "integration test",
                "regression test",
                "test coverage",
                "pytest",
                "test",
                "tests",
            ],
        ),
        (
            PlanningCategory.DOCUMENTATION,
            [
                "documentation",
                "readme",
                "docstring",
                "changelog",
                "user guide",
                "docs",
                "doc",
                "comment",
            ],
        ),
        (
            PlanningCategory.PERFORMANCE_WORK,
            [
                "performance",
                "optimize",
                "speed up",
                "benchmark",
                "latency",
                "profiling",
                "memory leak",
                "throughput",
            ],
        ),
        (
            PlanningCategory.REPOSITORY_ANALYSIS,
            [
                "analyze repository",
                "repository analysis",
                "analyze codebase",
                "map repository",
                "architecture overview",
                "explore codebase",
                "scan repo",
            ],
        ),
        (
            PlanningCategory.FEATURE_IMPLEMENTATION,
            [
                "feature",
                "implement",
                "build",
                "create",
                "develop",
                "add",
                "support",
                "new",
            ],
        ),
    ]

    _SMALL_TRIGGERS: list[str] = [
        "readme",
        "typo",
        "docstring",
        "comment",
        "minor",
        "trivial",
        "quick",
        "small",
        "spelling",
    ]

    _LARGE_TRIGGERS: list[str] = [
        "auth",
        "authentication",
        "database",
        "multi-service",
        "end-to-end",
        "full pipeline",
        "architecture",
        "infrastructure",
        "migration",
        "large",
        "complex",
        "security audit",
    ]

    @classmethod
    def normalize_goal(cls, text: str) -> str:
        """Normalize goal string deterministically (lower, strip punctuation, collapse space)."""
        lowered = text.lower().strip()
        # Replace non-alphanumeric chars (except spaces) with space
        sanitized = re.sub(r"[^\w\s]", " ", lowered)
        return re.sub(r"\s+", " ", sanitized).strip()

    def classify(self, goal: str) -> ClassificationResult:
        """Classify a raw goal string into category, complexity, and provenance metadata."""
        normalized = self.normalize_goal(goal)
        rules_matched: list[str] = []

        # 1. Category Classification
        category = PlanningCategory.GENERIC_TASK
        for cat, keywords in self._CATEGORY_RULES:
            for kw in keywords:
                # Match full word or phrase boundary
                pattern = r"\b" + re.escape(kw) + r"\b"
                if re.search(pattern, normalized):
                    category = cat
                    rules_matched.append(f"category_match:{cat.value}:{kw}")
                    break
            if category != PlanningCategory.GENERIC_TASK:
                break

        if category == PlanningCategory.GENERIC_TASK:
            rules_matched.append("category_match:generic_task:fallback")

        # 2. Complexity Tier Classification
        words = normalized.split()
        word_count = len(words)
        complexity = ComplexityTier.MEDIUM

        # Check for explicitly small triggers or very short simple goals
        small_matched = [
            t for t in self._SMALL_TRIGGERS if re.search(r"\b" + re.escape(t) + r"\b", normalized)
        ]
        large_matched = [
            t for t in self._LARGE_TRIGGERS if re.search(r"\b" + re.escape(t) + r"\b", normalized)
        ]

        if small_matched and not large_matched and word_count <= 6:
            complexity = ComplexityTier.SMALL
            rules_matched.append(f"complexity_match:SMALL:trigger:{','.join(small_matched)}")
        elif large_matched or word_count >= 12:
            complexity = ComplexityTier.LARGE
            if large_matched:
                rules_matched.append(f"complexity_match:LARGE:trigger:{','.join(large_matched)}")
            else:
                rules_matched.append(f"complexity_match:LARGE:word_count:{word_count}")
        else:
            complexity = ComplexityTier.MEDIUM
            rules_matched.append("complexity_match:MEDIUM:default")

        return ClassificationResult(
            category=category,
            complexity_tier=complexity,
            rule_identifiers=rules_matched,
            normalized_goal=normalized,
        )


__all__ = ["ClassificationResult", "ComplexityTier", "PlanningCategory", "TaskClassifier"]
