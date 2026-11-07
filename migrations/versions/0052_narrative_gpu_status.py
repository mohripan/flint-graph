"""Whether the GPU machine is up, so the Studio can say so (ADR 0069).

Revision ID: 0052_narrative_gpu_status
Revises: 0051_generation_waits
"""

import sqlalchemy as sa
from alembic import op

revision = "0052_narrative_gpu_status"
down_revision = "0051_generation_waits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "narrative_gpu_status",
        sa.Column("name", sa.String(length=32), primary_key=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("detail", sa.String(length=40), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('ready','stopped','starting','stopping','unavailable')",
            name="ck_narrative_gpu_status_state",
        ),
    )


def downgrade() -> None:
    op.drop_table("narrative_gpu_status")
