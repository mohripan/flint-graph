"""Durable live progress for assistant turns: steps, thinking and reply text (#171).

Revision ID: 0023_narrative_turn_events
Revises: 0022_narrative_characters
"""

import sqlalchemy as sa
from alembic import op

revision = "0023_narrative_turn_events"
down_revision = "0022_narrative_characters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "narrative_assistant_turn_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("turn_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["turn_id", "thread_id", "project_id", "tenant_id"],
            [
                "narrative_assistant_turns.id",
                "narrative_assistant_turns.thread_id",
                "narrative_assistant_turns.project_id",
                "narrative_assistant_turns.tenant_id",
            ],
            name="fk_narrative_assistant_turn_event_turn",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "turn_id", "sequence", name="uq_narrative_assistant_turn_event_sequence"
        ),
        sa.CheckConstraint("sequence > 0", name="ck_narrative_assistant_turn_event_sequence"),
        sa.CheckConstraint("attempt >= 0", name="ck_narrative_assistant_turn_event_attempt"),
        sa.CheckConstraint(
            "kind IN ('step','thinking','text','status')",
            name="ck_narrative_assistant_turn_event_kind",
        ),
    )


def downgrade() -> None:
    op.drop_table("narrative_assistant_turn_events")
