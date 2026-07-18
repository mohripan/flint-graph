"""Add logical document deletion timestamp.

Revision ID: 0013_document_deleted_at
Revises: 0012_document_lifecycle_cleanup
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_document_deleted_at"
down_revision: str | None = "0012_document_lifecycle_cleanup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_documents_tenant_deleted_at", "documents", ["tenant_id", "deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_documents_tenant_deleted_at", table_name="documents")
    op.drop_column("documents", "deleted_at")
