"""Stage 5 persistence: initial learning_events / agent_passports /
agent_passport_buckets tables.

Hand-authored to mirror `app.persistence.models` column-for-column (rather
than a full-metadata `--autogenerate`, which would also sweep in the
pre-existing, unrelated workflow-state-machine tables that already exist
without their own migration history). Deliberately has no foreign key to
`workflows`/`workflow_steps`: `LearningEventRecord.workflow_id`/`step_id`
are plain opaque string columns, matching `app.persistence.models`'
"workflow state-machine ORM remains separate from learning models"
invariant even at the schema level, so this migration can run standalone
with no ordering dependency on however the workflow tables are migrated.

Uses only standard SQLAlchemy/PostgreSQL-portable column types (String,
Integer, Float, Boolean, JSON, DateTime(timezone=True)) -- no
PostgreSQL-dialect-specific or Supabase-specific SQL anywhere.

Revision ID: stage5_persistence_0001
Revises:
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "stage5_persistence_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "learning_events",
        sa.Column("event_id", sa.String(length=128), primary_key=True),
        sa.Column("workflow_id", sa.String(length=128), nullable=False),
        sa.Column("step_id", sa.String(length=128), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("agent_type", sa.String(length=64), nullable=False),
        sa.Column("runtime_kind", sa.String(length=32), nullable=True),
        sa.Column("task_type", sa.String(length=128), nullable=True),
        sa.Column("repository_id", sa.String(length=256), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=True),
        sa.Column("execution_status", sa.String(length=32), nullable=False),
        sa.Column("failure_category", sa.String(length=64), nullable=True),
        sa.Column("verification_status", sa.String(length=32), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancelled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("real_cost", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempt_number >= 1", name="ck_learning_events_attempt_number"),
    )
    op.create_index(
        "ix_learning_events_workflow_id", "learning_events", ["workflow_id"], unique=False
    )
    op.create_index(
        "ix_learning_events_agent_type", "learning_events", ["agent_type"], unique=False
    )
    op.create_index("ix_learning_events_task_type", "learning_events", ["task_type"], unique=False)
    op.create_index(
        "ix_learning_events_repository_id", "learning_events", ["repository_id"], unique=False
    )
    op.create_index(
        "ix_learning_events_created_at", "learning_events", ["created_at"], unique=False
    )
    op.create_index(
        "idx_learning_events_agent_created",
        "learning_events",
        ["agent_type", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_learning_events_task_agent",
        "learning_events",
        ["task_type", "agent_type"],
        unique=False,
    )
    op.create_index(
        "idx_learning_events_repo_agent",
        "learning_events",
        ["repository_id", "agent_type"],
        unique=False,
    )

    op.create_table(
        "agent_passports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("agent_type", sa.String(length=64), nullable=False, unique=True),
        sa.Column("execution_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancellation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("median_latency_ms", sa.Float(), nullable=True),
        sa.Column("p95_latency_ms", sa.Float(), nullable=True),
        sa.Column("failure_categories", sa.JSON(), nullable=True),
        sa.Column("low_sample_size", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("known_cost_usd_average", sa.Float(), nullable=True),
        sa.Column("known_cost_sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_passports_agent_type", "agent_passports", ["agent_type"], unique=True)

    op.create_table(
        "agent_passport_buckets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("agent_type", sa.String(length=64), nullable=False),
        sa.Column("bucket_type", sa.String(length=32), nullable=False),
        sa.Column("bucket_key", sa.String(length=256), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("verified_success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("verification_failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "verification_inconclusive_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("human_review_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("verification_sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("verified_success_rate", sa.Float(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancel_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_rate", sa.Float(), nullable=True),
        sa.Column("p50_latency", sa.Float(), nullable=True),
        sa.Column("p95_latency", sa.Float(), nullable=True),
        sa.Column("low_sample_size", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "agent_type", "bucket_type", "bucket_key", name="uq_agent_passport_bucket"
        ),
    )
    op.create_index(
        "ix_agent_passport_buckets_agent_type",
        "agent_passport_buckets",
        ["agent_type"],
        unique=False,
    )
    op.create_index(
        "idx_passport_bucket_query",
        "agent_passport_buckets",
        ["agent_type", "bucket_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("agent_passport_buckets")
    op.drop_table("agent_passports")
    op.drop_table("learning_events")
