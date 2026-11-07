"""On your own server nothing is charged, so there is no balance to keep (ADR 0075).

The history of what people used stays. Only the balance goes: the starting entry, and the "left"
figure on each charge. Anyone who also holds a grant keeps every entry, because those are real.

Revision ID: 0057_own_server_is_unlimited
Revises: 0056_own_credits
"""

import sqlalchemy as sa
from alembic import op

revision = "0057_own_server_is_unlimited"
down_revision = "0056_own_credits"
branch_labels = None
depends_on = None

_HAD_ONLY_A_BALANCE = (
    "user_id IN (SELECT user_id FROM own_credits) "
    "AND user_id NOT IN (SELECT user_id FROM access_grants)"
)


def upgrade() -> None:
    op.execute(f"DELETE FROM credit_ledger WHERE change = 'join' AND {_HAD_ONLY_A_BALANCE}")
    op.execute(f"UPDATE credit_ledger SET balance = NULL WHERE {_HAD_ONLY_A_BALANCE}")
    op.drop_table("own_credits")


def downgrade() -> None:
    op.create_table(
        "own_credits",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
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
        sa.CheckConstraint("credits >= 0", name="ck_own_credits_credits"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
