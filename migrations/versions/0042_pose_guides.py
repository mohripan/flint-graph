"""Frozen seated body guidance.
Revision ID: 0042_pose_guides
Revises: 0041_pose_repairs
"""

import sqlalchemy as sa
from alembic import op

revision = "0042_pose_guides"
down_revision = "0041_pose_repairs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "narrative_pose_guides",
        sa.Column("job_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("guide", sa.JSON(), nullable=False),
        sa.Column("guide_sha256", sa.String(64), nullable=False),
        sa.Column("control_manifest_sha256", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["narrative_pose_jobs.job_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["job_id", "project_id", "tenant_id"],
            [
                "narrative_image_jobs.id",
                "narrative_image_jobs.project_id",
                "narrative_image_jobs.tenant_id",
            ],
            ondelete="RESTRICT",
        ),
    )


def downgrade() -> None:
    op.drop_table("narrative_pose_guides")
