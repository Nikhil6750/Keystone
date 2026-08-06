"""Shared enumerations for the vNext contract layer.

`app.models.enums` remains the source of truth for persisted workflow/step
status (unchanged in this stage); these enums describe concepts that do not
exist in the current schema yet: aggregate agent readiness, capability tags,
execution outcome, and benchmark evaluators.
"""

from enum import StrEnum


class AgentStatus(StrEnum):
    """Aggregate readiness signal for routing and passport evidence.

    Deliberately coarser than `app.adapters.connection`'s
    `InstallationStatus`/`AuthenticationStatus`/`ConnectionStatus` trio, which
    remain the fine-grained diagnostic detail surfaced by the connection-
    verification API. This is the single signal routing needs to decide
    whether an agent is a viable candidate at all.
    """

    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class AgentCapability(StrEnum):
    """Capability tags an agent adapter can declare and a task can require."""

    CODE_GENERATION = "code_generation"
    CODE_REVIEW = "code_review"
    TEST_GENERATION = "test_generation"
    TEST_EXECUTION = "test_execution"
    DEBUGGING = "debugging"
    REFACTORING = "refactoring"
    DOCUMENTATION = "documentation"
    PLANNING = "planning"
    GENERAL_REASONING = "general_reasoning"
    FILE_EDITING = "file_editing"
    SHELL_EXECUTION = "shell_execution"


class AgentExecutionStatus(StrEnum):
    """Terminal outcome of one `AgentAdapter.execute()` call."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class BenchmarkEvaluatorType(StrEnum):
    """Objective evaluators a benchmark task may use. No subjective rankings."""

    EXACT_MATCH = "exact_match"
    JSON_SCHEMA = "json_schema"
    REGEX = "regex"
    EXIT_CODE = "exit_code"
    UNIT_TEST = "unit_test"
    BUILD = "build"
    LINT = "lint"
    TYPE_CHECK = "type_check"
    FILE_DIFF = "file_diff"
    HUMAN_REVIEWED = "human_reviewed"
