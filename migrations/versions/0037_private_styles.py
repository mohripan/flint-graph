"""Private project style training ledger and frozen pose bindings.

Revision ID: 0037_private_styles
Revises: 0036_pose_references
"""

import sqlalchemy as sa
from alembic import op

revision = "0037_private_styles"
down_revision = "0036_pose_references"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "narrative_style_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column(
            "author_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        *[
            sa.Column(key, sa.String(64), nullable=False)
            for key in ("request_hash", "model_manifest_sha256", "dataset_sha256", "recipe_sha256")
        ],
        sa.Column("images", sa.JSON(), nullable=False),
        sa.Column("trigger", sa.String(48), nullable=False),
        sa.Column("steps", sa.Integer(), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid()),
        sa.Column("execution_token", sa.Uuid()),
        sa.Column("activity_attempt", sa.Integer(), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.Column("weights_key", sa.String(500)),
        sa.Column("weights_sha256", sa.String(64)),
        sa.Column("weights_size", sa.Integer()),
        sa.Column("losses", sa.JSON()),
        sa.Column("runtime", sa.JSON()),
        sa.Column("tracking_run_id", sa.String(64)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["narrative_projects.id", "narrative_projects.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_style_job_key"),
        sa.UniqueConstraint("id", "project_id", "tenant_id", name="uq_style_job_scope"),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','failed','cancelled')",
            name="ck_style_status",
        ),
        sa.CheckConstraint(
            "steps BETWEEN 20 AND 400 AND progress BETWEEN 0 AND steps", name="ck_style_progress"
        ),
        sa.CheckConstraint("seed BETWEEN 0 AND 4294967295", name="ck_style_seed"),
    )
    op.create_index(
        "ix_style_jobs_workspace", "narrative_style_jobs", ["tenant_id", "status", "created_at"]
    )
    op.create_table(
        "narrative_pose_styles",
        sa.Column("job_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("style_id", sa.Uuid(), nullable=False),
        sa.Column("strength", sa.Float(), nullable=False),
        sa.Column("weights_sha256", sa.String(64), nullable=False),
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
            ["style_id", "project_id", "tenant_id"],
            [
                "narrative_style_jobs.id",
                "narrative_style_jobs.project_id",
                "narrative_style_jobs.tenant_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("strength BETWEEN 0.1 AND 1", name="ck_pose_style_strength"),
    )


def downgrade():
    op.drop_table("narrative_pose_styles")
    op.drop_table("narrative_style_jobs")
