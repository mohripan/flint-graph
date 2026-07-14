"""Add answer faithfulness persistence.

Revision ID: 0011_answer_faithfulness
Revises: 0010_query_run_ledger
Create Date: 2026-07-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_answer_faithfulness"
down_revision: str | None = "0010_query_run_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "query_runs",
        sa.Column(
            "abstained",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column("query_runs", sa.Column("abstain_reason", sa.String(length=500), nullable=True))
    op.add_column(
        "query_runs",
        sa.Column(
            "supported_claim_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "query_runs",
        sa.Column(
            "unsupported_claim_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column("query_runs", sa.Column("support_method", sa.String(length=100), nullable=True))
    op.add_column("query_runs", sa.Column("answer_provider", sa.String(length=100), nullable=True))

    op.create_table(
        "query_answer_claims",
        sa.Column("query_run_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("claim_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("citation_ids", sa.JSON(), nullable=False),
        sa.Column("support_status", sa.String(length=32), nullable=False),
        sa.Column("support_score", sa.Float(), nullable=False),
        sa.Column("support_reason", sa.String(length=1000), nullable=False),
        sa.Column("method", sa.String(length=100), nullable=False),
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
            "claim_index",
            name="uq_query_answer_claims_run_index",
        ),
    )
    op.create_index(
        "ix_query_answer_claims_run_index",
        "query_answer_claims",
        ["query_run_id", "claim_index"],
    )
    op.create_index(
        "ix_query_answer_claims_tenant_status",
        "query_answer_claims",
        ["tenant_id", "support_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_query_answer_claims_tenant_status", table_name="query_answer_claims")
    op.drop_index("ix_query_answer_claims_run_index", table_name="query_answer_claims")
    op.drop_table("query_answer_claims")

    op.drop_column("query_runs", "answer_provider")
    op.drop_column("query_runs", "support_method")
    op.drop_column("query_runs", "unsupported_claim_count")
    op.drop_column("query_runs", "supported_claim_count")
    op.drop_column("query_runs", "abstain_reason")
    op.drop_column("query_runs", "abstained")
