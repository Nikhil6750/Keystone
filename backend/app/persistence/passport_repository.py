"""Agent Passport Repository for Stage 5 Derived Aggregate Metrics Persistence."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.engine.learning.events import LearningEvent
from app.engine.learning.passport import LearningPassport, rebuild_passport
from app.persistence.execution_repository import ExecutionHistoryRepository
from app.persistence.models import AgentPassportBucketRecord, AgentPassportRecord


def _make_tz_aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class AgentPassportRepository:
    """Repository handling persistence, retrieval, and derived rebuilds
    of `LearningPassport` aggregate metrics.
    """

    def create_or_update_passport(
        self, session: Session, passport: LearningPassport
    ) -> tuple[AgentPassportRecord, list[AgentPassportBucketRecord]]:
        """Persist or update `LearningPassport` summary and bucket records."""
        agent_type = passport.passport.agent_type
        updated_at = _make_tz_aware(passport.passport.updated_at) or datetime.now(UTC)

        # 1. Main Passport Summary Record
        summary = session.scalars(
            select(AgentPassportRecord).where(AgentPassportRecord.agent_type == agent_type)
        ).first()

        if not summary:
            summary = AgentPassportRecord(agent_type=agent_type)
            session.add(summary)

        summary.execution_count = passport.passport.execution_count
        summary.success_count = passport.passport.success_count
        summary.failure_count = passport.passport.failure_count
        summary.cancellation_count = passport.passport.cancellation_count
        summary.retry_count = passport.passport.retry_count
        summary.median_latency_ms = passport.passport.median_latency_ms
        summary.p95_latency_ms = passport.passport.p95_latency_ms
        summary.failure_categories = passport.passport.failure_categories
        summary.low_sample_size = passport.passport.low_sample_size
        summary.last_succeeded_at = _make_tz_aware(passport.passport.last_succeeded_at)
        summary.last_verified_at = _make_tz_aware(passport.passport.last_verified_at)
        summary.known_cost_usd_average = passport.known_cost_usd_average
        summary.known_cost_sample_count = passport.known_cost_sample_count
        summary.updated_at = updated_at

        # 2. Bucket Records
        bucket_records: list[AgentPassportBucketRecord] = []

        # Overall Bucket
        overall_rec = self._upsert_bucket(
            session=session,
            agent_type=agent_type,
            bucket_type="OVERALL",
            bucket_key="overall",
            bucket=passport.overall_metrics,
            verification=passport.overall_verification,
            updated_at=updated_at,
        )
        bucket_records.append(overall_rec)

        # Task Type Buckets
        for key, bucket in passport.task_type_buckets.items():
            rec = self._upsert_bucket(
                session=session,
                agent_type=agent_type,
                bucket_type="TASK_TYPE",
                bucket_key=key,
                bucket=bucket.metrics,
                verification=bucket.verification,
                updated_at=updated_at,
            )
            bucket_records.append(rec)

        # Repository Buckets
        for key, bucket in passport.repository_buckets.items():
            rec = self._upsert_bucket(
                session=session,
                agent_type=agent_type,
                bucket_type="REPOSITORY",
                bucket_key=key,
                bucket=bucket.metrics,
                verification=bucket.verification,
                updated_at=updated_at,
            )
            bucket_records.append(rec)

        # Capability Buckets
        for key, bucket in passport.capability_buckets.items():
            rec = self._upsert_bucket(
                session=session,
                agent_type=agent_type,
                bucket_type="CAPABILITY",
                bucket_key=key,
                bucket=bucket.metrics,
                verification=bucket.verification,
                updated_at=updated_at,
            )
            bucket_records.append(rec)

        # Repository + Task Type Joint Buckets
        for (repo_id, t_type), bucket in passport.repository_task_type_buckets.items():
            joint_key = f"{repo_id}::{t_type}"
            rec = self._upsert_bucket(
                session=session,
                agent_type=agent_type,
                bucket_type="REPOSITORY_TASK_TYPE",
                bucket_key=joint_key,
                bucket=bucket.metrics,
                verification=bucket.verification,
                updated_at=updated_at,
            )
            bucket_records.append(rec)

        return summary, bucket_records

    def _upsert_bucket(
        self,
        session: Session,
        agent_type: str,
        bucket_type: str,
        bucket_key: str,
        bucket: Any,
        verification: Any,
        updated_at: datetime,
    ) -> AgentPassportBucketRecord:
        rec = session.scalars(
            select(AgentPassportBucketRecord).where(
                AgentPassportBucketRecord.agent_type == agent_type,
                AgentPassportBucketRecord.bucket_type == bucket_type,
                AgentPassportBucketRecord.bucket_key == bucket_key,
            )
        ).first()

        if not rec:
            rec = AgentPassportBucketRecord(
                agent_type=agent_type,
                bucket_type=bucket_type,
                bucket_key=bucket_key,
            )
            session.add(rec)

        success_count = bucket.success_count
        failure_count = bucket.failure_count
        sample_count = bucket.execution_count
        success_rate = (success_count / sample_count) if sample_count > 0 else None

        v_success = verification.verified_success_count if verification else 0
        v_failure = verification.verification_failure_count if verification else 0
        v_inconclusive = verification.verification_inconclusive_count if verification else 0
        v_human = verification.human_review_count if verification else 0
        v_samples = verification.verification_sample_count if verification else 0
        v_rate = verification.verified_success_rate if verification else None

        rec.sample_count = sample_count
        rec.success_count = success_count
        rec.failure_count = failure_count
        rec.verified_success_count = v_success
        rec.verification_failure_count = v_failure
        rec.verification_inconclusive_count = v_inconclusive
        rec.human_review_count = v_human
        rec.verification_sample_count = v_samples
        rec.verified_success_rate = v_rate
        rec.success_rate = success_rate
        rec.p50_latency = bucket.median_latency_ms
        rec.p95_latency = getattr(bucket, "p95_latency_ms", None)
        rec.low_sample_size = bucket.low_sample_size
        rec.updated_at = updated_at

        return rec

    def get_passport(self, session: Session, agent_type: str) -> AgentPassportRecord | None:
        """Retrieve `AgentPassportRecord` by `agent_type`."""
        return session.scalars(
            select(AgentPassportRecord).where(AgentPassportRecord.agent_type == agent_type)
        ).first()

    def list_passports(self, session: Session) -> Sequence[AgentPassportRecord]:
        """List all stored `AgentPassportRecord` instances."""
        return session.scalars(
            select(AgentPassportRecord).order_by(AgentPassportRecord.agent_type.asc())
        ).all()

    def get_metric_buckets(
        self, session: Session, agent_type: str, bucket_type: str | None = None
    ) -> Sequence[AgentPassportBucketRecord]:
        """Retrieve metric buckets for a given agent type."""
        stmt = select(AgentPassportBucketRecord).where(
            AgentPassportBucketRecord.agent_type == agent_type
        )
        if bucket_type:
            stmt = stmt.where(AgentPassportBucketRecord.bucket_type == bucket_type)
        return session.scalars(stmt.order_by(AgentPassportBucketRecord.bucket_key.asc())).all()

    def replace_rebuild_aggregate_state(
        self, session: Session, agent_type: str, passport: LearningPassport
    ) -> tuple[AgentPassportRecord, list[AgentPassportBucketRecord]]:
        """Replace all derived aggregate state for `agent_type` with new `passport`."""
        session.execute(
            delete(AgentPassportBucketRecord).where(
                AgentPassportBucketRecord.agent_type == agent_type
            )
        )
        return self.create_or_update_passport(session, passport)

    def rebuild_passport_from_history(
        self, session: Session, agent_type: str, updated_at: datetime | None = None
    ) -> LearningPassport:
        """Rebuild `LearningPassport` directly from raw execution events in database.

        Source of Truth Rule: Query raw `learning_events` table for `agent_type`,
        run standard `rebuild_passport` pure function, and update stored aggregate tables.
        """
        now = _make_tz_aware(updated_at) or datetime.now(UTC)
        history_repo = ExecutionHistoryRepository()
        event_records = history_repo.query_by_agent(session, agent_type=agent_type, limit=10000)

        domain_events: list[LearningEvent] = [
            history_repo.record_to_domain(rec) for rec in event_records
        ]

        passport = rebuild_passport(domain_events, agent_type=agent_type, updated_at=now)
        self.replace_rebuild_aggregate_state(session, agent_type=agent_type, passport=passport)
        return passport


__all__ = ["AgentPassportRepository"]
