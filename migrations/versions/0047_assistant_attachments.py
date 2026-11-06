"""What the creator attached to a message from the project's library (ADR 0062).

Revision ID: 0047_assistant_attachments
Revises: 0046_assistant_actions
"""

import sqlalchemy as sa
from alembic import op

revision = "0047_assistant_attachments"
down_revision = "0046_assistant_actions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "narrative_assistant_turns",
        sa.Column("attachments", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade() -> None:
    op.drop_column("narrative_assistant_turns", "attachments")
