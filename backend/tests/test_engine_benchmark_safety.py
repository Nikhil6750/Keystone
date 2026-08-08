"""Tests for Stage 7A Benchmark Engine evidence safety and input bounds."""

import pytest

from app.contracts.enums import AgentExecutionStatus
from app.contracts.errors import FailureCategory
from app.engine.benchmark.errors import MalformedBenchmarkObservationError
from app.engine.benchmark.models import BenchmarkExecutionObservation
from app.engine.verification.errors import UnsafeEvidenceError
from app.engine.verification.evaluators import ObservedOutcome


def test_observation_prevents_inconsistent_status_category_pairing() -> None:
    # SUCCEEDED cannot have failure_category
    with pytest.raises(MalformedBenchmarkObservationError, match="failure_category must be None"):
        BenchmarkExecutionObservation(
            agent_type="a1",
            execution_status=AgentExecutionStatus.SUCCEEDED,
            duration_ms=10.0,
            observed_outcome=ObservedOutcome(data={"output": "x"}),
            failure_category=FailureCategory.INTERNAL_ERROR,
        )

    # FAILED requires failure_category
    with pytest.raises(MalformedBenchmarkObservationError, match="failure_category is required"):
        BenchmarkExecutionObservation(
            agent_type="a1",
            execution_status=AgentExecutionStatus.FAILED,
            duration_ms=10.0,
            observed_outcome=ObservedOutcome(data={"error": "failed"}),
            failure_category=None,
        )


def test_observation_prevents_negative_duration_or_cost() -> None:
    with pytest.raises(MalformedBenchmarkObservationError, match="duration_ms must be finite"):
        BenchmarkExecutionObservation(
            agent_type="a1",
            execution_status=AgentExecutionStatus.SUCCEEDED,
            duration_ms=-5.0,
            observed_outcome=ObservedOutcome(data={"output": "x"}),
        )

    with pytest.raises(MalformedBenchmarkObservationError, match="cost_usd must be finite"):
        BenchmarkExecutionObservation(
            agent_type="a1",
            execution_status=AgentExecutionStatus.SUCCEEDED,
            duration_ms=5.0,
            observed_outcome=ObservedOutcome(data={"output": "x"}),
            cost_usd=-0.01,
        )


def test_observed_outcome_rejects_reasoning_shaped_keys() -> None:
    with pytest.raises(UnsafeEvidenceError, match="chain_of_thought"):
        ObservedOutcome(data={"chain_of_thought": "secret reasoning"})
