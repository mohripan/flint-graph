"""Ordered approved pose references, backward compatible with single-source jobs.

Revision ID: 0036_pose_references
Revises: 0035_narrative_poses
"""

import sqlalchemy as sa
from alembic import op

revision = "0036_pose_references"
down_revision = "0035_narrative_poses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "narrative_pose_references",
        sa.Column("job_id", sa.Uuid(), primary_key=True),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("view", sa.String(16), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["asset_id", "project_id", "tenant_id"],
            ["narrative_assets.id", "narrative_assets.project_id", "narrative_assets.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("job_id", "asset_id", name="uq_pose_reference_asset"),
        sa.CheckConstraint("position IN (0,1)", name="ck_pose_reference_position"),
        sa.CheckConstraint(
            "(position=0 AND view='primary') OR "
            "(position=1 AND view IN ('front','side','back','detail'))",
            name="ck_pose_reference_view",
        ),
    )


def downgrade() -> None:
    op.drop_table("narrative_pose_references")
