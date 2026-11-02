"""Frozen local repairs of existing pose candidates.

Revision ID: 0041_pose_repairs
Revises: 0040_anatomy_reviews
"""

import sqlalchemy as sa
from alembic import op

revision = "0041_pose_repairs"
down_revision = "0040_anatomy_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "narrative_pose_repairs",
        sa.Column("job_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("source_asset_id", sa.Uuid(), nullable=False),
        sa.Column("source_job_id", sa.Uuid(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("source_box", sa.JSON(), nullable=True),
        sa.Column("box", sa.JSON(), nullable=False),
        sa.Column("instruction", sa.String(300), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["narrative_pose_jobs.job_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_job_id"], ["narrative_pose_jobs.job_id"], ondelete="RESTRICT"
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
            ["source_job_id", "project_id", "tenant_id"],
            [
                "narrative_image_jobs.id",
                "narrative_image_jobs.project_id",
                "narrative_image_jobs.tenant_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_asset_id", "project_id", "tenant_id"],
            ["narrative_assets.id", "narrative_assets.project_id", "narrative_assets.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "width BETWEEN 32 AND 768 AND height BETWEEN 32 AND 1152", name="ck_pose_repair_size"
        ),
    )


def downgrade() -> None:
    op.drop_table("narrative_pose_repairs")
