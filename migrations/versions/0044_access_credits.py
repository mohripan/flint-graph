"""Credits: balances, unlimited access, priced charges and a credit ledger (ADR 0059).

Existing invitations and grants keep NULL credits: they stay on ADR 0058's caps until
an operator sets a balance.

Revision ID: 0044_access_credits
Revises: 0043_access_invitations
"""

import sqlalchemy as sa
from alembic import op

revision = "0044_access_credits"
down_revision = "0043_access_invitations"
branch_labels = None
depends_on = None

_CHANGES = ("join", "charge", "add", "remove", "set", "unlimited", "limited")


def upgrade() -> None:
    for table in ("access_invitations", "access_grants"):
        op.add_column(table, sa.Column("credits", sa.Integer(), nullable=True))
        op.add_column(
            table,
            sa.Column("unlimited", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.create_check_constraint(f"ck_{table}_credits", table, "credits IS NULL OR credits >= 0")
    op.add_column("usage_charges", sa.Column("item", sa.String(40), nullable=True))
    op.create_table(
        "credit_ledger",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("change", sa.String(12), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("balance", sa.Integer(), nullable=True),
        sa.Column("item", sa.String(40), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("subject", sa.String(120), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.String(300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "change IN (" + ", ".join(f"'{change}'" for change in _CHANGES) + ")",
            name="ck_credit_ledger_change",
        ),
        sa.CheckConstraint("balance IS NULL OR balance >= 0", name="ck_credit_ledger_balance"),
    )
    op.create_index("ix_credit_ledger_user_time", "credit_ledger", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_credit_ledger_user_time", table_name="credit_ledger")
    op.drop_table("credit_ledger")
    op.drop_column("usage_charges", "item")
    for table in ("access_grants", "access_invitations"):
        op.drop_constraint(f"ck_{table}_credits", table, type_="check")
        op.drop_column(table, "unlimited")
        op.drop_column(table, "credits")
