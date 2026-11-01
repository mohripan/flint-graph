"""Pinned reference/model plans for character poses.

Revision ID: 0035_narrative_poses
Revises: 0034_narrative_looks
"""

import sqlalchemy as sa
from alembic import op

revision = "0035_narrative_poses"
down_revision = "0034_narrative_looks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "narrative_pose_jobs",
        sa.Column("job_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("character_id", sa.String(64), nullable=False),
        sa.Column("look_id", sa.Uuid(), nullable=False),
        sa.Column("pose", sa.Text(), nullable=False),
        sa.Column("model_manifest_sha256", sa.String(64), nullable=False),
        sa.Column("cutout_manifest_sha256", sa.String(64), nullable=True),
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
        "ix_pose_jobs_character", "narrative_pose_jobs", ["tenant_id", "project_id", "character_id"]
    )


def downgrade() -> None:
    op.drop_table("narrative_pose_jobs")
