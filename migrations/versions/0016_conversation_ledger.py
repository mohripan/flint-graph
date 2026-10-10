"""Tenant-authoritative conversations and ordered query-run references.

Revision ID: 0016_conversation_ledger
Revises: 0015_operational_telemetry
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_conversation_ledger"
down_revision: str | None = "0015_operational_telemetry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint("uq_query_runs_id_tenant", "query_runs", ["id", "tenant_id"])
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("next_turn_number", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_conversations_id_tenant"),
        sa.CheckConstraint("next_turn_number > 0", name="ck_conversations_next_turn_positive"),
    )
    op.create_index(
        "ix_conversations_tenant_created", "conversations", ["tenant_id", "created_at", "id"]
    )
    op.create_table(
        "conversation_turns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("query_run_id", sa.Uuid(), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["conversation_id", "tenant_id"],
            ["conversations.id", "conversations.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["query_run_id", "tenant_id"],
            ["query_runs.id", "query_runs.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("conversation_id", "turn_number", name="uq_conversation_turn_number"),
        sa.UniqueConstraint("conversation_id", "idempotency_key", name="uq_conversation_turn_key"),
        sa.UniqueConstraint("query_run_id", name="uq_conversation_turn_run"),
        sa.CheckConstraint("turn_number > 0", name="ck_conversation_turn_positive"),
    )


def downgrade() -> None:
    op.drop_table("conversation_turns")
    op.drop_index("ix_conversations_tenant_created", table_name="conversations")
    op.drop_table("conversations")
    op.drop_constraint("uq_query_runs_id_tenant", "query_runs", type_="unique")
