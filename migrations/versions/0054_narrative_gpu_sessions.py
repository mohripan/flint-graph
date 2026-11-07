"""GPU time used, for the daily cap on a machine that sleeps (ADR 0070).

Revision ID: 0054_narrative_gpu_sessions
Revises: 0053_narrative_music_jobs
"""

import sqlalchemy as sa
from alembic import op

revision = "0054_narrative_gpu_sessions"
down_revision = "0053_narrative_music_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "narrative_gpu_sessions",
        sa.Column("started_at", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("narrative_gpu_sessions")
