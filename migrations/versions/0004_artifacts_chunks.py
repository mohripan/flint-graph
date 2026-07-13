"""Add document artifacts and chunks.

Revision ID: 0004_artifacts_chunks
Revises: 0003_version_cancelled
Create Date: 2026-07-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_artifacts_chunks"
down_revision: str | None = "0003_version_cancelled"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

artifact_type = sa.Enum(
    "raw",
    "normalized",
    "chunk_manifest",
    "extraction",
    name="document_artifact_type",
    native_enum=False,
    length=32,
)


def upgrade() -> None:
    op.create_table(
        "document_artifacts",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_type", artifact_type, nullable=False),
        sa.Column("object_uri", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_version_id",
            "artifact_type",
            name="uq_document_artifacts_version_type",
        ),
    )
    op.create_index(
        "ix_document_artifacts_document_version",
        "document_artifacts",
        ["document_version_id"],
    )
    op.create_index("ix_document_artifacts_document_id", "document_artifacts", ["document_id"])
    op.create_index("ix_document_artifacts_tenant_id", "document_artifacts", ["tenant_id"])

    op.create_table(
        "document_chunks",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.String(length=100), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("chunk_hash", sa.String(length=128), nullable=False),
        sa.Column("source_element_ids", sa.JSON(), nullable=False),
        sa.Column("heading_path", sa.JSON(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("source_offsets", sa.JSON(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_version_id",
            "chunk_index",
            name="uq_document_chunks_version_index",
        ),
        sa.UniqueConstraint(
            "document_version_id",
            "chunk_id",
            name="uq_document_chunks_version_chunk_id",
        ),
    )
    op.create_index(
        "ix_document_chunks_document_version",
        "document_chunks",
        ["document_version_id", "chunk_index"],
    )
    op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"])
    op.create_index("ix_document_chunks_tenant_id", "document_chunks", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("document_chunks")
    op.drop_table("document_artifacts")
