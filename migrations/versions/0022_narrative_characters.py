"""Character profiles, local image-generation jobs and immutable images (ADR 0039).

Revision ID: 0022_narrative_characters
Revises: 0021_narrative_project_layout
"""

import sqlalchemy as sa
from alembic import op

revision = "0022_narrative_characters"
down_revision = "0021_narrative_project_layout"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def _project_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["project_id", "tenant_id"],
        ["narrative_projects.id", "narrative_projects.tenant_id"],
        name=name,
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.create_table(
        "narrative_image_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("character_id", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("appearance", sa.Text(), nullable=False),
        sa.Column("character_type", sa.String(length=16), nullable=False),
        sa.Column("framing", sa.String(length=16), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("negative_prompt", sa.Text(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("steps", sa.Integer(), nullable=False),
        sa.Column("guidance", sa.Float(), nullable=False),
        sa.Column("seeds", sa.JSON(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("execution_token", sa.Uuid(), nullable=True),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=True),
        sa.Column("activity_attempt", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("runtime", sa.JSON(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("truncated", sa.Boolean(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        _project_fk("fk_narrative_image_job_project"),
        sa.UniqueConstraint("id", "project_id", "tenant_id", name="uq_narrative_image_job_scope"),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_narrative_image_job_key"),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','failed','cancelled')",
            name="ck_narrative_image_job_status",
        ),
        sa.CheckConstraint(
            "(status = 'running' AND execution_token IS NOT NULL) OR "
            "(status <> 'running' AND execution_token IS NULL)",
            name="ck_narrative_image_job_execution_fence",
        ),
        sa.CheckConstraint(
            "status <> 'completed' OR NOT cancel_requested",
            name="ck_narrative_image_job_not_cancelled_completed",
        ),
        sa.CheckConstraint(
            "(workflow_run_id IS NULL AND activity_attempt IS NULL) OR "
            "(workflow_run_id IS NOT NULL AND activity_attempt IS NOT NULL "
            "AND activity_attempt >= 0)",
            name="ck_narrative_image_job_workflow_owner",
        ),
        sa.CheckConstraint("count BETWEEN 1 AND 4", name="ck_narrative_image_job_count"),
        sa.CheckConstraint("progress BETWEEN 0 AND count", name="ck_narrative_image_job_progress"),
    )
    op.create_index(
        "ix_narrative_image_job_active",
        "narrative_image_jobs",
        ["tenant_id"],
        postgresql_where=sa.text("status IN ('queued','running')"),
    )
    op.create_index(
        "ix_narrative_image_job_run_status", "narrative_image_jobs", ["status", "workflow_run_id"]
    )
    op.create_index(
        "ix_narrative_image_job_character",
        "narrative_image_jobs",
        ["project_id", "character_id", "created_at", "id"],
    )
    op.create_table(
        "narrative_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("job_index", sa.Integer(), nullable=True),
        sa.Column("character_id", sa.String(length=64), nullable=True),
        sa.Column("media_type", sa.String(length=32), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("thumbnail_sha256", sa.String(length=64), nullable=False),
        sa.Column("thumbnail_size_bytes", sa.Integer(), nullable=False),
        sa.Column("thumbnail_width", sa.Integer(), nullable=False),
        sa.Column("thumbnail_height", sa.Integer(), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("license", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("approved_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        _project_fk("fk_narrative_asset_project"),
        sa.ForeignKeyConstraint(
            ["job_id", "project_id", "tenant_id"],
            [
                "narrative_image_jobs.id",
                "narrative_image_jobs.project_id",
                "narrative_image_jobs.tenant_id",
            ],
            name="fk_narrative_asset_job",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "project_id", "tenant_id", name="uq_narrative_asset_scope"),
        sa.UniqueConstraint("job_id", "job_index", name="uq_narrative_asset_job_index"),
        sa.CheckConstraint(
            "status IN ('candidate','approved','discarded')", name="ck_narrative_asset_status"
        ),
        sa.CheckConstraint("kind IN ('character_portrait')", name="ck_narrative_asset_kind"),
        sa.CheckConstraint("media_type = 'image/png'", name="ck_narrative_asset_media_type"),
        sa.CheckConstraint(
            "size_bytes > 0 AND width > 0 AND height > 0", name="ck_narrative_asset_shape"
        ),
        sa.CheckConstraint(
            "status <> 'approved' OR approved_at IS NOT NULL",
            name="ck_narrative_asset_approval",
        ),
    )
    op.create_index(
        "ix_narrative_assets_project", "narrative_assets", ["project_id", "created_at", "id"]
    )
    op.create_table(
        "narrative_character_profiles",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("character_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("appearance", sa.Text(), nullable=False),
        sa.Column("character_type", sa.String(length=16), nullable=False),
        sa.Column("framing", sa.String(length=16), nullable=False),
        sa.Column("portrait_asset_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("project_id", "character_id"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        _project_fk("fk_narrative_character_profile_project"),
        sa.ForeignKeyConstraint(
            ["portrait_asset_id", "project_id", "tenant_id"],
            [
                "narrative_assets.id",
                "narrative_assets.project_id",
                "narrative_assets.tenant_id",
            ],
            name="fk_narrative_character_profile_portrait",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("version > 0", name="ck_narrative_character_profile_version"),
    )


def downgrade() -> None:
    op.drop_table("narrative_character_profiles")
    op.drop_index("ix_narrative_assets_project", table_name="narrative_assets")
    op.drop_table("narrative_assets")
    op.drop_index("ix_narrative_image_job_character", table_name="narrative_image_jobs")
    op.drop_index("ix_narrative_image_job_run_status", table_name="narrative_image_jobs")
    op.drop_index("ix_narrative_image_job_active", table_name="narrative_image_jobs")
    op.drop_table("narrative_image_jobs")
