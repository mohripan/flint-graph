"""Add transactional outbox messages.

Revision ID: 0002_outbox_messages
Revises: 0001_foundation
Create Date: 2026-07-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_outbox_messages"
down_revision: str | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

outbox_status = sa.Enum(
    "pending",
    "published",
    "failed",
    name="outbox_message_status",
    native_enum=False,
    length=32,
)


def upgrade() -> None:
    op.create_table(
        "outbox_messages",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("topic", sa.String(length=100), nullable=False),
        sa.Column("aggregate_type", sa.String(length=100), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("headers", sa.JSON(), nullable=False),
        sa.Column("status", outbox_status, nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=200), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outbox_messages_tenant_id", "outbox_messages", ["tenant_id"])
    op.create_index(
        "ix_outbox_status_available",
        "outbox_messages",
        ["status", "available_at"],
    )
    op.create_index(
        "ix_outbox_aggregate",
        "outbox_messages",
        ["aggregate_type", "aggregate_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_aggregate", table_name="outbox_messages")
    op.drop_index("ix_outbox_status_available", table_name="outbox_messages")
    op.drop_index("ix_outbox_messages_tenant_id", table_name="outbox_messages")
    op.drop_table("outbox_messages")
