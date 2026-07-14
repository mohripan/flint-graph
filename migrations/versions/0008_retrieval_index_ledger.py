"""Add retrieval index ledger.

Revision ID: 0008_retrieval_index_ledger
Revises: 0007_staged_resolution_state
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_retrieval_index_ledger"
down_revision: str | None = "0007_staged_resolution_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

retrieval_index_scope = sa.Enum(
    "global",
    "tenant",
    name="retrieval_index_scope",
    native_enum=False,
    length=32,
)

retrieval_index_version_status = sa.Enum(
    "building",
    "active",
    "deprecated",
    "failed",
    name="retrieval_index_version_status",
    native_enum=False,
    length=32,
)

index_backfill_job_status = sa.Enum(
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
    name="index_backfill_job_status",
    native_enum=False,
    length=32,
)


def upgrade() -> None:
    op.create_table(
        "retrieval_index_versions",
        sa.Column("scope", retrieval_index_scope, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("embedding_provider", sa.String(length=100), nullable=False),
        sa.Column("embedding_model", sa.String(length=200), nullable=False),
        sa.Column("vector_dimension", sa.Integer(), nullable=False),
        sa.Column("embedding_config_hash", sa.String(length=128), nullable=False),
        sa.Column("chunking_schema_version", sa.String(length=32), nullable=False),
        sa.Column("chunking_config_hash", sa.String(length=128), nullable=False),
        sa.Column("lexical_schema_version", sa.String(length=32), nullable=False),
        sa.Column("neo4j_vector_index_name", sa.String(length=200), nullable=False),
        sa.Column("neo4j_vector_property_name", sa.String(length=200), nullable=False),
        sa.Column("opensearch_index_name", sa.String(length=200), nullable=False),
        sa.Column("opensearch_alias_name", sa.String(length=200), nullable=False),
        sa.Column("status", retrieval_index_version_status, nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "(scope = 'global' AND tenant_id IS NULL) OR "
            "(scope = 'tenant' AND tenant_id IS NOT NULL)",
            name="ck_retrieval_index_versions_scope_tenant",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_retrieval_index_versions_tenant_id",
        "retrieval_index_versions",
        ["tenant_id"],
    )
    op.create_index(
        "ix_retrieval_index_versions_scope_status",
        "retrieval_index_versions",
        ["scope", "tenant_id", "status"],
    )
    op.create_index(
        "uq_retrieval_index_versions_active_global",
        "retrieval_index_versions",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND tenant_id IS NULL"),
    )
    op.create_index(
        "uq_retrieval_index_versions_active_tenant",
        "retrieval_index_versions",
        ["tenant_id", "status"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND tenant_id IS NOT NULL"),
    )

    op.create_table(
        "chunk_embeddings",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("retrieval_index_version_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.String(length=100), nullable=False),
        sa.Column("chunk_hash", sa.String(length=128), nullable=False),
        sa.Column("vector_dimension", sa.Integer(), nullable=False),
        sa.Column("vector", sa.JSON(), nullable=False),
        sa.Column("provider_metadata", sa.JSON(), nullable=False),
        sa.Column("request_hash", sa.String(length=128), nullable=False),
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
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["retrieval_index_version_id"],
            ["retrieval_index_versions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "retrieval_index_version_id",
            "document_version_id",
            "chunk_id",
            "chunk_hash",
            name="uq_chunk_embeddings_index_chunk_hash",
        ),
    )
    op.create_index("ix_chunk_embeddings_tenant_id", "chunk_embeddings", ["tenant_id"])
    op.create_index("ix_chunk_embeddings_document_id", "chunk_embeddings", ["document_id"])
    op.create_index(
        "ix_chunk_embeddings_document_version_id",
        "chunk_embeddings",
        ["document_version_id"],
    )
    op.create_index(
        "ix_chunk_embeddings_retrieval_index_version_id",
        "chunk_embeddings",
        ["retrieval_index_version_id"],
    )
    op.create_index(
        "ix_chunk_embeddings_tenant_version",
        "chunk_embeddings",
        ["tenant_id", "retrieval_index_version_id"],
    )
    op.create_index(
        "ix_chunk_embeddings_document_version",
        "chunk_embeddings",
        ["document_version_id"],
    )

    op.create_table(
        "index_backfill_jobs",
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("retrieval_index_version_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("document_version_id", sa.Uuid(), nullable=True),
        sa.Column("status", index_backfill_job_status, nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("processed_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("checkpoint", sa.JSON(), nullable=False),
        sa.Column("last_error", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["retrieval_index_version_id"],
            ["retrieval_index_versions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_index_backfill_jobs_tenant_id", "index_backfill_jobs", ["tenant_id"])
    op.create_index("ix_index_backfill_jobs_document_id", "index_backfill_jobs", ["document_id"])
    op.create_index(
        "ix_index_backfill_jobs_document_version_id",
        "index_backfill_jobs",
        ["document_version_id"],
    )
    op.create_index(
        "ix_index_backfill_jobs_retrieval_index_version_id",
        "index_backfill_jobs",
        ["retrieval_index_version_id"],
    )
    op.create_index(
        "ix_index_backfill_jobs_tenant_status",
        "index_backfill_jobs",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_index_backfill_jobs_version_status",
        "index_backfill_jobs",
        ["retrieval_index_version_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_index_backfill_jobs_version_status", table_name="index_backfill_jobs")
    op.drop_index("ix_index_backfill_jobs_tenant_status", table_name="index_backfill_jobs")
    op.drop_index(
        "ix_index_backfill_jobs_retrieval_index_version_id",
        table_name="index_backfill_jobs",
    )
    op.drop_index(
        "ix_index_backfill_jobs_document_version_id",
        table_name="index_backfill_jobs",
    )
    op.drop_index("ix_index_backfill_jobs_document_id", table_name="index_backfill_jobs")
    op.drop_index("ix_index_backfill_jobs_tenant_id", table_name="index_backfill_jobs")
    op.drop_table("index_backfill_jobs")

    op.drop_index("ix_chunk_embeddings_document_version", table_name="chunk_embeddings")
    op.drop_index("ix_chunk_embeddings_tenant_version", table_name="chunk_embeddings")
    op.drop_index(
        "ix_chunk_embeddings_retrieval_index_version_id",
        table_name="chunk_embeddings",
    )
    op.drop_index("ix_chunk_embeddings_document_version_id", table_name="chunk_embeddings")
    op.drop_index("ix_chunk_embeddings_document_id", table_name="chunk_embeddings")
    op.drop_index("ix_chunk_embeddings_tenant_id", table_name="chunk_embeddings")
    op.drop_table("chunk_embeddings")

    op.drop_index(
        "uq_retrieval_index_versions_active_tenant",
        table_name="retrieval_index_versions",
        postgresql_where=sa.text("status = 'active' AND tenant_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_retrieval_index_versions_active_global",
        table_name="retrieval_index_versions",
        postgresql_where=sa.text("status = 'active' AND tenant_id IS NULL"),
    )
    op.drop_index(
        "ix_retrieval_index_versions_scope_status",
        table_name="retrieval_index_versions",
    )
    op.drop_index("ix_retrieval_index_versions_tenant_id", table_name="retrieval_index_versions")
    op.drop_table("retrieval_index_versions")
