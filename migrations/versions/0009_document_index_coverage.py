"""Add document index coverage.

Revision ID: 0009_document_index_coverage
Revises: 0008_retrieval_index_ledger
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_document_index_coverage"
down_revision: str | None = "0008_retrieval_index_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

document_index_coverage_status = sa.Enum(
    "running",
    "completed",
    "failed",
    "cancelled",
    name="document_index_coverage_status",
    native_enum=False,
    length=32,
)


def upgrade() -> None:
    op.create_table(
        "document_index_coverages",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("retrieval_index_version_id", sa.Uuid(), nullable=False),
        sa.Column("status", document_index_coverage_status, nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("embedded_count", sa.Integer(), nullable=False),
        sa.Column("vector_count", sa.Integer(), nullable=False),
        sa.Column("lexical_count", sa.Integer(), nullable=False),
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
            name="uq_document_index_coverages_version_document_version",
        ),
    )
    op.create_index(
        "ix_document_index_coverages_tenant_id",
        "document_index_coverages",
        ["tenant_id"],
    )
    op.create_index(
        "ix_document_index_coverages_document_id",
        "document_index_coverages",
        ["document_id"],
    )
    op.create_index(
        "ix_document_index_coverages_document_version_id",
        "document_index_coverages",
        ["document_version_id"],
    )
    op.create_index(
        "ix_document_index_coverages_retrieval_index_version_id",
        "document_index_coverages",
        ["retrieval_index_version_id"],
    )
    op.create_index(
        "ix_document_index_coverages_tenant_status",
        "document_index_coverages",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_document_index_coverages_document_version",
        "document_index_coverages",
        ["document_version_id"],
    )
    op.create_index(
        "ix_document_index_coverages_index_version",
        "document_index_coverages",
        ["retrieval_index_version_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_index_coverages_index_version",
        table_name="document_index_coverages",
    )
    op.drop_index(
        "ix_document_index_coverages_document_version",
        table_name="document_index_coverages",
    )
    op.drop_index(
        "ix_document_index_coverages_tenant_status",
        table_name="document_index_coverages",
    )
    op.drop_index(
        "ix_document_index_coverages_retrieval_index_version_id",
        table_name="document_index_coverages",
    )
    op.drop_index(
        "ix_document_index_coverages_document_version_id",
        table_name="document_index_coverages",
    )
    op.drop_index(
        "ix_document_index_coverages_document_id",
        table_name="document_index_coverages",
    )
    op.drop_index(
        "ix_document_index_coverages_tenant_id",
        table_name="document_index_coverages",
    )
    op.drop_table("document_index_coverages")
