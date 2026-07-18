"""Add document lifecycle and projection cleanup ledgers.

Revision ID: 0012_document_lifecycle_cleanup
Revises: 0011_answer_faithfulness
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_document_lifecycle_cleanup"
down_revision: str | None = "0011_answer_faithfulness"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_lifecycle_events",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_document_lifecycle_events_tenant_document_created",
        "document_lifecycle_events",
        ["tenant_id", "document_id", "created_at"],
    )
    op.create_index(
        "ix_document_lifecycle_events_document_version",
        "document_lifecycle_events",
        ["document_version_id"],
    )
    op.create_index(
        "ix_document_lifecycle_events_tenant_id",
        "document_lifecycle_events",
        ["tenant_id"],
    )
    op.create_index(
        "ix_document_lifecycle_events_document_version_id",
        "document_lifecycle_events",
        ["document_version_id"],
    )

    op.create_table(
        "document_projection_cleanups",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("retrieval_index_version_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stale_reason", sa.String(length=64), nullable=False),
        sa.Column("chunk_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("vector_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lexical_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["retrieval_index_version_id"],
            ["retrieval_index_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_version_id",
            "retrieval_index_version_id",
            "stale_reason",
            name="uq_document_projection_cleanups_version_index_reason",
        ),
    )
    op.create_index(
        "ix_document_projection_cleanups_tenant_status",
        "document_projection_cleanups",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_document_projection_cleanups_document",
        "document_projection_cleanups",
        ["document_id", "created_at"],
    )
    op.create_index(
        "ix_document_projection_cleanups_tenant_id",
        "document_projection_cleanups",
        ["tenant_id"],
    )
    op.create_index(
        "ix_document_projection_cleanups_document_version_id",
        "document_projection_cleanups",
        ["document_version_id"],
    )
    op.create_index(
        "ix_document_projection_cleanups_retrieval_index_version_id",
        "document_projection_cleanups",
        ["retrieval_index_version_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_projection_cleanups_retrieval_index_version_id",
        table_name="document_projection_cleanups",
    )
    op.drop_index(
        "ix_document_projection_cleanups_document_version_id",
        table_name="document_projection_cleanups",
    )
    op.drop_index(
        "ix_document_projection_cleanups_tenant_id",
        table_name="document_projection_cleanups",
    )
    op.drop_index(
        "ix_document_projection_cleanups_document",
        table_name="document_projection_cleanups",
    )
    op.drop_index(
        "ix_document_projection_cleanups_tenant_status",
        table_name="document_projection_cleanups",
    )
    op.drop_table("document_projection_cleanups")

    op.drop_index(
        "ix_document_lifecycle_events_document_version_id",
        table_name="document_lifecycle_events",
    )
    op.drop_index(
        "ix_document_lifecycle_events_tenant_id",
        table_name="document_lifecycle_events",
    )
    op.drop_index(
        "ix_document_lifecycle_events_document_version",
        table_name="document_lifecycle_events",
    )
    op.drop_index(
        "ix_document_lifecycle_events_tenant_document_created",
        table_name="document_lifecycle_events",
    )
    op.drop_table("document_lifecycle_events")
