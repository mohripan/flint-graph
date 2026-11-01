"""Private reviewed-look training targets.

Revision ID: 0038_character_adapters
Revises: 0037_private_styles
"""

import sqlalchemy as sa
from alembic import op

revision = "0038_character_adapters"
down_revision = "0037_private_styles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "narrative_character_adapters",
        sa.Column("job_id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("character_id", sa.String(64), nullable=False),
        sa.Column("look_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id", "project_id", "tenant_id"],
            [
                "narrative_style_jobs.id",
                "narrative_style_jobs.project_id",
                "narrative_style_jobs.tenant_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["look_id", "project_id", "tenant_id", "character_id"],
            [
                "narrative_character_looks.id",
                "narrative_character_looks.project_id",
                "narrative_character_looks.tenant_id",
                "narrative_character_looks.character_id",
            ],
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_character_adapter_look",
        "narrative_character_adapters",
        ["tenant_id", "project_id", "character_id", "look_id"],
    )


def downgrade() -> None:
    op.drop_table("narrative_character_adapters")
