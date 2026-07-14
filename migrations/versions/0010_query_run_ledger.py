"""Add query run ledger.

Revision ID: 0010_query_run_ledger
Revises: 0009_document_index_coverage
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_query_run_ledger"
down_revision: str | None = "0009_document_index_coverage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

query_run_status = sa.Enum(
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
    name="query_run_status",
    native_enum=False,
    length=32,
)


def upgrade() -> None:
    op.create_table(
        "query_runs",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("retrieval_index_version_id", sa.Uuid(), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("normalized_query_hash", sa.String(length=128), nullable=False),
        sa.Column("status", query_run_status, nullable=False),
        sa.Column("classification_label", sa.String(length=32), nullable=True),
        sa.Column("retrieval_strategy", sa.String(length=100), nullable=True),
        sa.Column("classification_confidence", sa.Float(), nullable=True),
        sa.Column("classification_metadata", sa.JSON(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("answer_citations", sa.JSON(), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("context_token_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_details", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["retrieval_index_version_id"],
            ["retrieval_index_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_query_runs_tenant_id", "query_runs", ["tenant_id"])
    op.create_index(
        "ix_query_runs_retrieval_index_version_id",
        "query_runs",
        ["retrieval_index_version_id"],
    )
    op.create_index(
        "ix_query_runs_tenant_status_created",
        "query_runs",
        ["tenant_id", "status", "created_at"],
    )
    op.create_index(
        "ix_query_runs_tenant_hash_created",
        "query_runs",
        ["tenant_id", "normalized_query_hash", "created_at"],
    )

    op.create_table(
        "query_run_events",
        sa.Column("query_run_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["query_run_id"], ["query_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "query_run_id",
            "sequence",
            name="uq_query_run_events_run_sequence",
        ),
    )
    op.create_index("ix_query_run_events_tenant_id", "query_run_events", ["tenant_id"])
    op.create_index(
        "ix_query_run_events_run_sequence",
        "query_run_events",
        ["query_run_id", "sequence"],
    )
    op.create_index(
        "ix_query_run_events_tenant_created",
        "query_run_events",
        ["tenant_id", "created_at"],
    )

    op.create_table(
        "query_run_linked_entities",
        sa.Column("query_run_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_entity_id", sa.Uuid(), nullable=True),
        sa.Column("mention_text", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("method", sa.String(length=100), nullable=False),
        sa.Column("candidate_entity_ids", sa.JSON(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["canonical_entity_id"],
            ["canonical_entities.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["query_run_id"], ["query_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_query_run_linked_entities_tenant_status",
        "query_run_linked_entities",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_query_run_linked_entities_run",
        "query_run_linked_entities",
        ["query_run_id"],
    )

    op.create_table(
        "query_run_candidates",
        sa.Column("query_run_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("retrieval_index_version_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("candidate_type", sa.String(length=32), nullable=False),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=500), nullable=False),
        sa.Column("text_preview", sa.Text(), nullable=True),
        sa.Column("raw_score", sa.Float(), nullable=False),
        sa.Column("normalized_score", sa.Float(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("fusion_score", sa.Float(), nullable=True),
        sa.Column("rerank_score", sa.Float(), nullable=True),
        sa.Column("rerank_rank", sa.Integer(), nullable=True),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["query_run_id"], ["query_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["retrieval_index_version_id"],
            ["retrieval_index_versions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "query_run_id",
            "dedupe_key",
            name="uq_query_run_candidates_run_dedupe",
        ),
    )
    op.create_index(
        "ix_query_run_candidates_tenant_source",
        "query_run_candidates",
        ["tenant_id", "source"],
    )
    op.create_index(
        "ix_query_run_candidates_run_rank",
        "query_run_candidates",
        ["query_run_id", "rank"],
    )

    op.create_table(
        "query_context_packs",
        sa.Column("query_run_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("pack_id", sa.String(length=200), nullable=False),
        sa.Column("pack_version", sa.Integer(), nullable=False),
        sa.Column("token_budget", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("selected_candidate_ids", sa.JSON(), nullable=False),
        sa.Column("citation_map", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["query_run_id"], ["query_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "query_run_id",
            "pack_version",
            name="uq_query_context_packs_run_version",
        ),
    )
    op.create_index(
        "ix_query_context_packs_run_version",
        "query_context_packs",
        ["query_run_id", "pack_version"],
    )

    op.create_table(
        "query_context_pack_records",
        sa.Column("query_context_pack_id", sa.Uuid(), nullable=False),
        sa.Column("query_run_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("context_id", sa.String(length=200), nullable=False),
        sa.Column("candidate_id", sa.String(length=300), nullable=False),
        sa.Column("citation_id", sa.String(length=100), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["query_context_pack_id"],
            ["query_context_packs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["query_run_id"], ["query_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "query_context_pack_id",
            "citation_id",
            name="uq_query_context_pack_records_pack_citation",
        ),
        sa.UniqueConstraint(
            "query_context_pack_id",
            "context_id",
            name="uq_query_context_pack_records_pack_context",
        ),
    )
    op.create_index(
        "ix_query_context_pack_records_pack",
        "query_context_pack_records",
        ["query_context_pack_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_query_context_pack_records_pack",
        table_name="query_context_pack_records",
    )
    op.drop_table("query_context_pack_records")

    op.drop_index("ix_query_context_packs_run_version", table_name="query_context_packs")
    op.drop_table("query_context_packs")

    op.drop_index("ix_query_run_candidates_run_rank", table_name="query_run_candidates")
    op.drop_index("ix_query_run_candidates_tenant_source", table_name="query_run_candidates")
    op.drop_table("query_run_candidates")

    op.drop_index(
        "ix_query_run_linked_entities_run",
        table_name="query_run_linked_entities",
    )
    op.drop_index(
        "ix_query_run_linked_entities_tenant_status",
        table_name="query_run_linked_entities",
    )
    op.drop_table("query_run_linked_entities")

    op.drop_index("ix_query_run_events_tenant_created", table_name="query_run_events")
    op.drop_index("ix_query_run_events_run_sequence", table_name="query_run_events")
    op.drop_index("ix_query_run_events_tenant_id", table_name="query_run_events")
    op.drop_table("query_run_events")

    op.drop_index("ix_query_runs_tenant_hash_created", table_name="query_runs")
    op.drop_index("ix_query_runs_tenant_status_created", table_name="query_runs")
    op.drop_index("ix_query_runs_retrieval_index_version_id", table_name="query_runs")
    op.drop_index("ix_query_runs_tenant_id", table_name="query_runs")
    op.drop_table("query_runs")
