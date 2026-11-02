"""Freeze a separate character adapter beside the existing pose style.

Revision ID: 0039_pose_adapter_stacks
Revises: 0038_character_adapters
"""

import sqlalchemy as sa
from alembic import op

revision = "0039_pose_adapter_stacks"
down_revision = "0038_character_adapters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "narrative_pose_character_adapters",
        sa.Column("job_id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("adapter_id", sa.Uuid(), nullable=False),
        sa.Column("strength", sa.Float(), nullable=False),
        sa.Column("weights_sha256", sa.String(64), nullable=False),
        sa.CheckConstraint("strength BETWEEN 0.1 AND 1", name="ck_pose_character_strength"),
        sa.ForeignKeyConstraint(["job_id"], ["narrative_pose_jobs.job_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["adapter_id"], ["narrative_character_adapters.job_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "project_id", "tenant_id"],
            [
                "narrative_image_jobs.id",
                "narrative_image_jobs.project_id",
                "narrative_image_jobs.tenant_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["adapter_id", "project_id", "tenant_id"],
            [
                "narrative_style_jobs.id",
                "narrative_style_jobs.project_id",
                "narrative_style_jobs.tenant_id",
            ],
            ondelete="RESTRICT",
        ),
    )


def downgrade() -> None:
    op.drop_table("narrative_pose_character_adapters")
