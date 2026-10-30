"""Immutable narrative releases, fenced jobs and private artifact metadata.

Revision ID: 0018_narrative_releases
Revises: 0017_narrative_projects
"""

import sqlalchemy as sa
from alembic import op

revision = "0018_narrative_releases"
down_revision = "0017_narrative_projects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "narrative_releases",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("creation_key", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("package_hash", sa.String(length=64), nullable=False),
        sa.Column("compiler_version", sa.String(length=32), nullable=False),
        sa.Column("runtime_version", sa.String(length=32), nullable=False),
        sa.Column("godot_version", sa.String(length=32), nullable=False),
        sa.Column("toolchain_sha256", sa.String(length=64), nullable=False),
        sa.Column("builder_image_digest", sa.String(length=71), nullable=False),
        sa.Column("creator_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["creator_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["revision_id", "project_id", "tenant_id"],
            [
                "narrative_revisions.id",
                "narrative_revisions.project_id",
                "narrative_revisions.tenant_id",
            ],
            name="fk_narrative_release_revision",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", "tenant_id", name="uq_narrative_release_scope"),
        sa.UniqueConstraint("project_id", "creation_key", name="uq_narrative_release_key"),
    )
    op.create_index(
        "ix_narrative_release_project_created",
        "narrative_releases",
        ["tenant_id", "project_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "narrative_release_jobs",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("retry_key", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("execution_token", sa.Uuid(), nullable=True),
        sa.Column("next_event_sequence", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint(
            "(status = 'running' AND execution_token IS NOT NULL) OR "
            "(status <> 'running' AND execution_token IS NULL)",
            name="ck_narrative_release_execution_fence",
        ),
        sa.CheckConstraint(
            "status <> 'completed' OR NOT cancel_requested",
            name="ck_narrative_release_not_cancelled_completed",
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','failed','cancelled')",
            name="ck_narrative_release_status",
        ),
        sa.CheckConstraint(
            "attempt_number > 0 AND next_event_sequence > 0", name="ck_narrative_release_sequences"
        ),
        sa.ForeignKeyConstraint(
            ["release_id", "project_id", "tenant_id"],
            [
                "narrative_releases.id",
                "narrative_releases.project_id",
                "narrative_releases.tenant_id",
            ],
            name="fk_narrative_release_job_release",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "release_id", "project_id", "tenant_id", name="uq_narrative_release_job_scope"
        ),
        sa.UniqueConstraint("release_id", "attempt_number", name="uq_narrative_release_attempt"),
        sa.UniqueConstraint("release_id", "retry_key", name="uq_narrative_release_retry_key"),
    )
    op.create_index(
        "ix_narrative_release_workspace_status",
        "narrative_release_jobs",
        ["tenant_id", "status"],
        unique=False,
    )
    op.create_index(
        "uq_narrative_release_active_job",
        "narrative_release_jobs",
        ["release_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued','running')"),
        sqlite_where=sa.text("status IN ('queued','running')"),
    )
    op.create_table(
        "narrative_release_events",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("sequence > 0", name="ck_narrative_release_event_sequence"),
        sa.ForeignKeyConstraint(
            ["job_id", "release_id", "project_id", "tenant_id"],
            [
                "narrative_release_jobs.id",
                "narrative_release_jobs.release_id",
                "narrative_release_jobs.project_id",
                "narrative_release_jobs.tenant_id",
            ],
            name="fk_narrative_release_event_job",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "sequence", name="uq_narrative_release_event_sequence"),
    )
    op.create_table(
        "narrative_release_artifacts",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "kind <> 'manifest' OR size_bytes <= 1048576", name="ck_narrative_release_manifest_size"
        ),
        sa.CheckConstraint(
            "kind IN ('source','web','manifest')", name="ck_narrative_release_artifact_kind"
        ),
        sa.CheckConstraint(
            "size_bytes > 0 AND size_bytes <= 67108864", name="ck_narrative_release_artifact_size"
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "release_id", "project_id", "tenant_id"],
            [
                "narrative_release_jobs.id",
                "narrative_release_jobs.release_id",
                "narrative_release_jobs.project_id",
                "narrative_release_jobs.tenant_id",
            ],
            name="fk_narrative_release_artifact_job",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("release_id", "kind", name="uq_narrative_release_artifact_kind"),
    )
    op.execute("""
        CREATE FUNCTION narrative_release_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Narrative release records are immutable' USING ERRCODE = '55000';
        END;
        $$
    """)
    for table in ["narrative_releases", "narrative_release_events", "narrative_release_artifacts"]:
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION narrative_release_immutable()"
        )


def downgrade() -> None:
    for table in ["narrative_releases", "narrative_release_events", "narrative_release_artifacts"]:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
    for table in [
        "narrative_release_artifacts",
        "narrative_release_events",
        "narrative_release_jobs",
        "narrative_releases",
    ]:
        op.drop_table(table)
    op.execute("DROP FUNCTION narrative_release_immutable()")
