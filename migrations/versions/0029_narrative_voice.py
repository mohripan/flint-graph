"""Character voices, local voice jobs and WAV voice clips in the library (ADR 0043).

Revision ID: 0029_narrative_voice
Revises: 0028_narrative_asset_folders
"""

import sqlalchemy as sa
from alembic import op

revision = "0029_narrative_voice"
down_revision = "0028_narrative_asset_folders"
branch_labels = None
depends_on = None

OLD_KINDS = "kind IN ('character_portrait','background','sprite','image','font')"
OLD_MEDIA = "media_type IN ('image/png','font/ttf','font/otf')"
OLD_SHAPE = (
    "size_bytes > 0 AND ((media_type = 'image/png' AND width > 0 AND height > 0) "
    "OR (media_type <> 'image/png' AND width IS NULL AND height IS NULL))"
)
KINDS = "kind IN ('character_portrait','background','sprite','image','font','voice')"
MEDIA = "media_type IN ('image/png','font/ttf','font/otf','audio/wav')"
SHAPE = (
    "size_bytes > 0 AND ((media_type = 'image/png' AND width > 0 AND height > 0 "
    "AND duration_ms IS NULL) OR (media_type = 'audio/wav' AND width IS NULL "
    "AND height IS NULL AND duration_ms > 0) OR (media_type IN ('font/ttf','font/otf') "
    "AND width IS NULL AND height IS NULL AND duration_ms IS NULL))"
)
ONE_JOB = "job_id IS NULL OR voice_job_id IS NULL"


def upgrade() -> None:
    op.add_column("narrative_character_profiles", sa.Column("voice", sa.String(32), nullable=True))
    op.create_table(
        "narrative_voice_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("character_id", sa.String(64), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("voice", sa.String(32), nullable=False),
        sa.Column("speed", sa.Float(), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("execution_token", sa.Uuid(), nullable=True),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=True),
        sa.Column("activity_attempt", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("model", sa.String(200), nullable=True),
        sa.Column("runtime", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *(
            sa.Column(
                name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
            )
            for name in ("created_at", "updated_at")
        ),
        sa.UniqueConstraint("id", "project_id", "tenant_id", name="uq_narrative_voice_job_scope"),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_narrative_voice_job_key"),
        sa.ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["narrative_projects.id", "narrative_projects.tenant_id"],
            name="fk_narrative_voice_job_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name="fk_narrative_voice_job_user",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','failed','cancelled')",
            name="ck_narrative_voice_job_status",
        ),
        sa.CheckConstraint(
            "(status = 'running' AND execution_token IS NOT NULL) OR "
            "(status <> 'running' AND execution_token IS NULL)",
            name="ck_narrative_voice_job_execution_fence",
        ),
        sa.CheckConstraint(
            "status <> 'completed' OR NOT cancel_requested",
            name="ck_narrative_voice_job_not_cancelled_completed",
        ),
        sa.CheckConstraint(
            "(workflow_run_id IS NULL AND activity_attempt IS NULL) OR "
            "(workflow_run_id IS NOT NULL AND activity_attempt IS NOT NULL "
            "AND activity_attempt >= 0)",
            name="ck_narrative_voice_job_workflow_owner",
        ),
        sa.CheckConstraint("count BETWEEN 1 AND 24", name="ck_narrative_voice_job_count"),
        sa.CheckConstraint("progress BETWEEN 0 AND count", name="ck_narrative_voice_job_progress"),
        sa.CheckConstraint("speed BETWEEN 0.7 AND 1.3", name="ck_narrative_voice_job_speed"),
    )
    op.create_index(
        "ix_narrative_voice_job_active",
        "narrative_voice_jobs",
        ["tenant_id"],
        postgresql_where=sa.text("status IN ('queued','running')"),
    )
    op.create_index(
        "ix_narrative_voice_job_run_status", "narrative_voice_jobs", ["status", "workflow_run_id"]
    )
    op.create_index(
        "ix_narrative_voice_job_character",
        "narrative_voice_jobs",
        ["project_id", "character_id", "created_at", "id"],
    )
    op.add_column("narrative_assets", sa.Column("duration_ms", sa.Integer(), nullable=True))
    op.add_column("narrative_assets", sa.Column("voice_job_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_narrative_asset_voice_job",
        "narrative_assets",
        "narrative_voice_jobs",
        ["voice_job_id", "project_id", "tenant_id"],
        ["id", "project_id", "tenant_id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_narrative_asset_voice_job_index", "narrative_assets", ["voice_job_id", "job_index"]
    )
    for name in (
        "ck_narrative_asset_kind",
        "ck_narrative_asset_media_type",
        "ck_narrative_asset_shape",
    ):
        op.drop_constraint(name, "narrative_assets", type_="check")
    op.create_check_constraint("ck_narrative_asset_kind", "narrative_assets", KINDS)
    op.create_check_constraint("ck_narrative_asset_media_type", "narrative_assets", MEDIA)
    op.create_check_constraint("ck_narrative_asset_shape", "narrative_assets", SHAPE)
    op.create_check_constraint("ck_narrative_asset_one_job", "narrative_assets", ONE_JOB)


def downgrade() -> None:
    op.drop_constraint("ck_narrative_asset_one_job", "narrative_assets", type_="check")
    for name in (
        "ck_narrative_asset_kind",
        "ck_narrative_asset_media_type",
        "ck_narrative_asset_shape",
    ):
        op.drop_constraint(name, "narrative_assets", type_="check")
    op.create_check_constraint("ck_narrative_asset_kind", "narrative_assets", OLD_KINDS)
    op.create_check_constraint("ck_narrative_asset_media_type", "narrative_assets", OLD_MEDIA)
    op.create_check_constraint("ck_narrative_asset_shape", "narrative_assets", OLD_SHAPE)
    op.drop_constraint("uq_narrative_asset_voice_job_index", "narrative_assets", type_="unique")
    op.drop_constraint("fk_narrative_asset_voice_job", "narrative_assets", type_="foreignkey")
    op.drop_column("narrative_assets", "voice_job_id")
    op.drop_column("narrative_assets", "duration_ms")
    op.drop_index("ix_narrative_voice_job_character", table_name="narrative_voice_jobs")
    op.drop_index("ix_narrative_voice_job_run_status", table_name="narrative_voice_jobs")
    op.drop_index("ix_narrative_voice_job_active", table_name="narrative_voice_jobs")
    op.drop_table("narrative_voice_jobs")
    op.drop_column("narrative_character_profiles", "voice")
