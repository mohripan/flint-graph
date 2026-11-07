"""Generated music: fenced jobs, their tracks and the assistant's action (ADR 0067).

Revision ID: 0053_narrative_music_jobs
Revises: 0052_narrative_gpu_status
"""

import sqlalchemy as sa
from alembic import op

revision = "0053_narrative_music_jobs"
down_revision = "0052_narrative_gpu_status"
branch_labels = None
depends_on = None

OLD_ONE_JOB = "job_id IS NULL OR voice_job_id IS NULL"
ONE_JOB = (
    "(CASE WHEN job_id IS NOT NULL THEN 1 ELSE 0 END) "
    "+ (CASE WHEN voice_job_id IS NOT NULL THEN 1 ELSE 0 END) "
    "+ (CASE WHEN music_job_id IS NOT NULL THEN 1 ELSE 0 END) <= 1"
)
OLD_ACTION_ONE_JOB = (
    "(CASE WHEN image_job_id IS NOT NULL THEN 1 ELSE 0 END) "
    "+ (CASE WHEN voice_job_id IS NOT NULL THEN 1 ELSE 0 END) "
    "+ (CASE WHEN child_thread_id IS NOT NULL THEN 1 ELSE 0 END) <= 1"
)
ACTION_ONE_JOB = (
    "(CASE WHEN image_job_id IS NOT NULL THEN 1 ELSE 0 END) "
    "+ (CASE WHEN voice_job_id IS NOT NULL THEN 1 ELSE 0 END) "
    "+ (CASE WHEN music_job_id IS NOT NULL THEN 1 ELSE 0 END) "
    "+ (CASE WHEN child_thread_id IS NOT NULL THEN 1 ELSE 0 END) <= 1"
)


OLD_USAGE = "kind IN ('image', 'voice', 'assistant', 'release', 'training')"
NEW_USAGE = "kind IN ('image', 'voice', 'assistant', 'release', 'training', 'music')"


def upgrade() -> None:
    op.drop_constraint("ck_usage_charges_kind", "usage_charges", type_="check")
    op.create_check_constraint("ck_usage_charges_kind", "usage_charges", NEW_USAGE)
    op.create_table(
        "narrative_music_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("seconds", sa.Integer(), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
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
        sa.UniqueConstraint("id", "project_id", "tenant_id", name="uq_narrative_music_job_scope"),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_narrative_music_job_key"),
        sa.ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["narrative_projects.id", "narrative_projects.tenant_id"],
            name="fk_narrative_music_job_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name="fk_narrative_music_job_user",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','failed','cancelled')",
            name="ck_narrative_music_job_status",
        ),
        sa.CheckConstraint(
            "(status = 'running' AND execution_token IS NOT NULL) OR "
            "(status <> 'running' AND execution_token IS NULL)",
            name="ck_narrative_music_job_execution_fence",
        ),
        sa.CheckConstraint(
            "status <> 'completed' OR NOT cancel_requested",
            name="ck_narrative_music_job_not_cancelled_completed",
        ),
        sa.CheckConstraint(
            "(workflow_run_id IS NULL AND activity_attempt IS NULL) OR "
            "(workflow_run_id IS NOT NULL AND activity_attempt IS NOT NULL "
            "AND activity_attempt >= 0)",
            name="ck_narrative_music_job_workflow_owner",
        ),
        sa.CheckConstraint("seconds BETWEEN 15 AND 180", name="ck_narrative_music_job_seconds"),
        sa.CheckConstraint("progress BETWEEN 0 AND 1", name="ck_narrative_music_job_progress"),
    )
    op.create_index(
        "ix_narrative_music_job_active",
        "narrative_music_jobs",
        ["tenant_id"],
        postgresql_where=sa.text("status IN ('queued','running')"),
    )
    op.create_index(
        "ix_narrative_music_job_run_status",
        "narrative_music_jobs",
        ["status", "workflow_run_id"],
    )
    op.add_column("narrative_assets", sa.Column("music_job_id", sa.Uuid(), nullable=True))
    op.create_unique_constraint(
        "uq_narrative_asset_music_job_index", "narrative_assets", ["music_job_id", "job_index"]
    )
    op.create_foreign_key(
        "fk_narrative_asset_music_job",
        "narrative_assets",
        "narrative_music_jobs",
        ["music_job_id", "project_id", "tenant_id"],
        ["id", "project_id", "tenant_id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint("ck_narrative_asset_one_job", "narrative_assets", type_="check")
    op.create_check_constraint("ck_narrative_asset_one_job", "narrative_assets", ONE_JOB)

    op.add_column("narrative_assistant_actions", sa.Column("music_job_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_narrative_assistant_action_music_job",
        "narrative_assistant_actions",
        "narrative_music_jobs",
        ["music_job_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "ck_narrative_assistant_action_one_job", "narrative_assistant_actions", type_="check"
    )
    op.create_check_constraint(
        "ck_narrative_assistant_action_one_job", "narrative_assistant_actions", ACTION_ONE_JOB
    )
    op.create_index(
        "ix_narrative_assistant_action_music_job",
        "narrative_assistant_actions",
        ["music_job_id"],
        postgresql_where=sa.text("music_job_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.execute("DELETE FROM usage_charges WHERE kind = 'music'")
    op.drop_constraint("ck_usage_charges_kind", "usage_charges", type_="check")
    op.create_check_constraint("ck_usage_charges_kind", "usage_charges", OLD_USAGE)
    op.drop_index(
        "ix_narrative_assistant_action_music_job", table_name="narrative_assistant_actions"
    )
    op.drop_constraint(
        "ck_narrative_assistant_action_one_job", "narrative_assistant_actions", type_="check"
    )
    op.drop_constraint(
        "fk_narrative_assistant_action_music_job",
        "narrative_assistant_actions",
        type_="foreignkey",
    )
    op.drop_column("narrative_assistant_actions", "music_job_id")
    op.create_check_constraint(
        "ck_narrative_assistant_action_one_job", "narrative_assistant_actions", OLD_ACTION_ONE_JOB
    )
    op.drop_constraint("ck_narrative_asset_one_job", "narrative_assets", type_="check")
    op.drop_constraint("fk_narrative_asset_music_job", "narrative_assets", type_="foreignkey")
    op.drop_constraint("uq_narrative_asset_music_job_index", "narrative_assets", type_="unique")
    op.drop_column("narrative_assets", "music_job_id")
    op.create_check_constraint("ck_narrative_asset_one_job", "narrative_assets", OLD_ONE_JOB)
    op.drop_index("ix_narrative_music_job_run_status", table_name="narrative_music_jobs")
    op.drop_index("ix_narrative_music_job_active", table_name="narrative_music_jobs")
    op.drop_table("narrative_music_jobs")
