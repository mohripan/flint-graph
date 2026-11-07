"""A balance for someone running their own server, separate from access grants (ADR 0074).

Revision ID: 0056_own_credits
Revises: 0055_project_trash
"""

import sqlalchemy as sa
from alembic import op

revision = "0056_own_credits"
down_revision = "0055_project_trash"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
    # Made on their own server, so it never counts against an allowance they get later.
    op.add_column(
        "usage_charges",
        sa.Column("own_server", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("usage_charges", "own_server")
    op.drop_table("own_credits")
