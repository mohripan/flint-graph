"""Versioned manual anatomy reviews shared by identical image bytes.

Revision ID: 0040_anatomy_reviews
Revises: 0039_pose_adapter_stacks
"""

import sqlalchemy as sa
from alembic import op

revision = "0040_anatomy_reviews"
down_revision = "0039_pose_adapter_stacks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "narrative_anatomy_reviews",
        sa.Column("tenant_id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), primary_key=True),
        sa.Column("sha256", sa.String(64), primary_key=True),
        sa.Column("anatomy", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["narrative_projects.id", "narrative_projects.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "anatomy IN ('acceptable','flawed','unknown')", name="ck_anatomy_review_verdict"
        ),
        sa.CheckConstraint("version > 0", name="ck_anatomy_review_version"),
    )
    op.create_index(
        "ix_candidate_review_hash",
        "narrative_candidate_reviews",
        ["tenant_id", "project_id", "candidate_sha256"],
    )


def downgrade() -> None:
    op.drop_index("ix_candidate_review_hash", table_name="narrative_candidate_reviews")
    op.drop_table("narrative_anatomy_reviews")
