"""Execution seam definitions for Stage 7A Benchmark Engine.

Defines the `BenchmarkExecutor` Protocol and a deterministic `FakeBenchmarkExecutor`
used for testing without calling external LLMs or connectors.
"""

from typing import Protocol

from app.engine.benchmark.models import BenchmarkCase, BenchmarkExecutionObservation


class BenchmarkExecutor(Protocol):
    """Protocol for executing a candidate agent on one benchmark case for one repetition."""

    def execute(
        self,
        *,
        agent_type: str,
        case: BenchmarkCase,
        repetition: int,
    ) -> BenchmarkExecutionObservation: ...


class FakeBenchmarkExecutor:
    """Configurable in-memory fake executor for deterministic testing.

    Accepts pre-configured observations keyed by `(agent_type, case_id)` or
    `(agent_type, case_id, repetition)`.
    """

    def __init__(
        self,
        responses: (
            dict[tuple[str, str], BenchmarkExecutionObservation]
            | dict[tuple[str, str, int], BenchmarkExecutionObservation]
            | None
        ) = None,
    ) -> None:
        self._responses = responses or {}

    def execute(
        self,
        *,
        agent_type: str,
        case: BenchmarkCase,
        repetition: int,
    ) -> BenchmarkExecutionObservation:
        # Check specific repetition key first
        rep_key = (agent_type, case.case_id, repetition)
        if rep_key in self._responses:
            return self._responses[rep_key]  # type: ignore[index]

        # Check default key without repetition
        default_key = (agent_type, case.case_id)
        if default_key in self._responses:
            return self._responses[default_key]  # type: ignore[index]

        raise KeyError(
            f"No fake benchmark execution observation registered for "
            f"agent_type='{agent_type}', case_id='{case.case_id}', repetition={repetition}"
        )


__all__ = ["BenchmarkExecutor", "FakeBenchmarkExecutor"]
