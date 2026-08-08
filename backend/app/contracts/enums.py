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
    """Capability tags an agent adapter can declare and a task can require.

    Most values describe *task-domain* capability (what kind of work the
    runtime can do). `RAW_COMPLETION`, `STRUCTURED_OUTPUT`, and
    `TOOL_CALLING` describe *interaction-mode* capability instead (how the
    runtime can be talked to) — kept in this same flat tag set rather than a
    second enum, so a task's `required_capabilities` list can freely mix
    both kinds without the Router needing to reconcile two vocabularies.
    """

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
    RAW_COMPLETION = "raw_completion"
    STRUCTURED_OUTPUT = "structured_output"
    TOOL_CALLING = "tool_calling"


class RuntimeKind(StrEnum):
    """What kind of execution runtime an `AgentDescriptor` describes.

    Purely classificatory — the Router/Planner use it to reason about the
    qualitative difference between an autonomous multi-turn CLI agent and a
    single-shot model completion endpoint; `AgentAdapter.execute()` stays
    the same uniform contract for every value, so this never causes a branch
    in the execution contract itself, only in how a candidate is scored.
    """

    AGENT_CLI = "agent_cli"
    MODEL_API = "model_api"
    LOCAL_MODEL = "local_model"
    HYBRID = "hybrid"


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
