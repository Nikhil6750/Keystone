"""Tests for the agent passport contracts."""

from datetime import UTC, datetime

from app.contracts.passports import AgentPassport, AgentPassportMetricBucket


def test_empty_history_passport_has_no_computed_latency() -> None:
    passport = AgentPassport.model_validate(
        {"agent_type": "claude_code", "updated_at": datetime.now(UTC)}
    )
    assert passport.execution_count == 0
    assert passport.median_latency_ms is None
    assert passport.low_sample_size is False


def test_small_sample_can_be_flagged() -> None:
    passport = AgentPassport.model_validate(
        {
            "agent_type": "codex",
            "execution_count": 2,
            "success_count": 2,
            "low_sample_size": True,
            "updated_at": datetime.now(UTC),
        }
    )
    assert passport.low_sample_size is True


def test_task_type_and_repository_metrics_are_independent_buckets() -> None:
    passport = AgentPassport.model_validate(
        {
            "agent_type": "claude_code",
            "task_type_metrics": {
                "code_generation": {"execution_count": 5, "success_count": 4}
            },
            "repository_metrics": {"repo-a": {"execution_count": 1, "low_sample_size": True}},
            "updated_at": datetime.now(UTC),
        }
    )
    assert passport.task_type_metrics["code_generation"].success_count == 4
    assert passport.repository_metrics["repo-a"].low_sample_size is True


def test_metric_bucket_defaults_to_zero_counts() -> None:
    bucket = AgentPassportMetricBucket.model_validate({})
    assert bucket.execution_count == 0
    assert bucket.success_count == 0
    assert bucket.failure_count == 0
