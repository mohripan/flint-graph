"""audit ledger, provider usage accounting, and query run usage rollups

Revision ID: 0015_operational_telemetry
Revises: 0014_identity_memberships
Create Date: 2026-07-26 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_operational_telemetry"
down_revision: str | None = "0014_identity_memberships"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

audit_action = sa.Enum(
    "user.provisioned",
    "workspace.created",
    "workspace.member_upserted",
    "document.created",
    "document.intake_created",
    "document.deleted",
    "ingestion_job.created",
    "ingestion_job.cancelled",
    "projection_cleanup.retried",
    "retrieval_index.bootstrapped",
    "index_backfill.started",
    "entity.merged",
    "entity.unmerged",
    "merge_review.decided",
    name="audit_action",
    native_enum=False,
    length=64,
)
audit_outcome = sa.Enum(
    "allowed",
    "denied",
    "failed",
    name="audit_outcome",
    native_enum=False,
    length=32,
)
provider_usage_operation = sa.Enum(
    "answer",
    "embedding",
    "extraction",
    "rerank",
    "faithfulness",
    name="provider_usage_operation",
    native_enum=False,
    length=32,
)


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_issuer", sa.String(length=500), nullable=True),
        sa.Column("actor_subject", sa.String(length=500), nullable=True),
        sa.Column("action", audit_action, nullable=False),
        sa.Column("outcome", audit_outcome, nullable=False),
        sa.Column("resource_type", sa.String(length=100), nullable=True),
        sa.Column("resource_id", sa.String(length=200), nullable=True),
        sa.Column("request_id", sa.String(length=200), nullable=True),
        sa.Column("client_ip", sa.String(length=100), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"])
    op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"])
    op.create_index("ix_audit_events_request_id", "audit_events", ["request_id"])
    op.create_index(
        "ix_audit_events_tenant_created", "audit_events", ["tenant_id", "created_at"]
    )
    op.create_index(
        "ix_audit_events_actor_created", "audit_events", ["actor_user_id", "created_at"]
    )
    op.create_index(
        "ix_audit_events_action_created", "audit_events", ["action", "created_at"]
    )

    op.create_table(
        "provider_usage_events",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("operation", provider_usage_operation, nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("embedded_item_count", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_micros", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("query_run_id", sa.Uuid(), nullable=True),
        sa.Column("ingestion_job_id", sa.Uuid(), nullable=True),
        sa.Column("document_version_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.String(length=200), nullable=True),
        sa.Column("workflow_id", sa.String(length=200), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["query_run_id"], ["query_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["ingestion_job_id"], ["ingestion_jobs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("input_tokens >= 0", name="ck_provider_usage_input_tokens"),
        sa.CheckConstraint("output_tokens >= 0", name="ck_provider_usage_output_tokens"),
    )
    op.create_index(
        "ix_provider_usage_events_tenant_id", "provider_usage_events", ["tenant_id"]
    )
    op.create_index(
        "ix_provider_usage_events_tenant_created",
        "provider_usage_events",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_provider_usage_events_tenant_operation_created",
        "provider_usage_events",
        ["tenant_id", "operation", "created_at"],
    )
    op.create_index(
        "ix_provider_usage_events_query_run", "provider_usage_events", ["query_run_id"]
    )

    # Rollups so query history renders without aggregating usage per run. Existing
    # rows predate accounting, so they backfill to zero tokens and a null cost.
    op.add_column(
        "query_runs",
        sa.Column(
            "provider_input_tokens", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "query_runs",
        sa.Column(
            "provider_output_tokens", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "query_runs",
        sa.Column(
            "provider_duration_ms", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "query_runs",
        sa.Column("provider_cost_micros", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("query_runs", "provider_cost_micros")
    op.drop_column("query_runs", "provider_duration_ms")
    op.drop_column("query_runs", "provider_output_tokens")
    op.drop_column("query_runs", "provider_input_tokens")

    op.drop_index("ix_provider_usage_events_query_run", table_name="provider_usage_events")
    op.drop_index(
        "ix_provider_usage_events_tenant_operation_created",
        table_name="provider_usage_events",
    )
    op.drop_index(
        "ix_provider_usage_events_tenant_created", table_name="provider_usage_events"
    )
    op.drop_index("ix_provider_usage_events_tenant_id", table_name="provider_usage_events")
    op.drop_table("provider_usage_events")

    op.drop_index("ix_audit_events_action_created", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_created", table_name="audit_events")
    op.drop_index("ix_audit_events_tenant_created", table_name="audit_events")
    op.drop_index("ix_audit_events_request_id", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_user_id", table_name="audit_events")
    op.drop_index("ix_audit_events_tenant_id", table_name="audit_events")
    op.drop_table("audit_events")
