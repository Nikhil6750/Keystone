"""Shared builders for Stage 8C.1 orchestration-service tests."""

from app.contracts.adapter import AgentDescriptor
from app.contracts.enums import AgentCapability, AgentStatus, RuntimeKind
from app.engine.routing.availability import CandidateAgent
from app.resilience.circuit_breaker import CircuitState

# A single executor output payload that satisfies every planner-template
# evaluator this codebase currently ships (exact_match/json_schema/regex
# are content-specific and not targeted here; build/lint/unit_test/
# type_check/exit_code/file_diff all pass with this shape).
RICH_SUCCESS_OUTPUT: dict[str, object] = {
    "output": "ok",
    "exit_code": 0,
    "tests_total": 5,
    "tests_failed": 0,
    "violation_count": 0,
    "error_count": 0,
    "diff": "diff --git a/x.py b/x.py",
    "files_changed": ["x.py"],
}


def build_candidate(
    agent_type: str,
    *,
    status: AgentStatus = AgentStatus.AVAILABLE,
    circuit_state: CircuitState = CircuitState.CLOSED,
    capabilities: list[AgentCapability] | None = None,
) -> CandidateAgent:
    """A `CandidateAgent` with every known capability by default -- tests
    that care about capability-based exclusion pass a narrower list
    explicitly."""
    return CandidateAgent(
        descriptor=AgentDescriptor(
            agent_type=agent_type,
            display_name=agent_type,
            runtime_kind=RuntimeKind.AGENT_CLI,
            capabilities=capabilities if capabilities is not None else list(AgentCapability),
        ),
        status=status,
        circuit_state=circuit_state,
    )


__all__ = ["RICH_SUCCESS_OUTPUT", "build_candidate"]
