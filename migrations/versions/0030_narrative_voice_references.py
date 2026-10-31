"""Private voice references with a consent declaration (#175, ADR 0044).

Revision ID: 0030_narrative_voice_references
Revises: 0029_narrative_voice
"""

import sqlalchemy as sa
from alembic import op

revision = "0030_narrative_voice_references"
down_revision = "0029_narrative_voice"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "narrative_voice_references",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("speaker_name", sa.String(120), nullable=False),
        sa.Column("consent", sa.String(16), nullable=False),
        sa.Column("consent_declared_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("consent_declared_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("sample_rate", sa.Integer(), nullable=False),
        sa.Column("channels", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.Uuid(), nullable=True),
        *(
            sa.Column(
                name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
            )
            for name in ("created_at", "updated_at")
        ),
        sa.UniqueConstraint(
            "id", "project_id", "tenant_id", name="uq_narrative_voice_reference_scope"
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["narrative_projects.id", "narrative_projects.tenant_id"],
            name="fk_narrative_voice_reference_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["consent_declared_by_user_id"],
            ["users.id"],
            name="fk_narrative_voice_reference_declarer",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by_user_id"],
            ["users.id"],
            name="fk_narrative_voice_reference_deleter",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "consent IN ('self','permission')", name="ck_narrative_voice_reference_consent"
        ),
        sa.CheckConstraint(
            "source IN ('upload','recording')", name="ck_narrative_voice_reference_source"
        ),
        sa.CheckConstraint(
            "(status = 'active' AND deleted_at IS NULL AND deleted_by_user_id IS NULL) OR "
            "(status = 'deleted' AND deleted_at IS NOT NULL AND deleted_by_user_id IS NOT NULL)",
            name="ck_narrative_voice_reference_status",
        ),
        sa.CheckConstraint(
            "duration_ms BETWEEN 5000 AND 30000 AND size_bytes > 0 AND channels IN (1, 2)",
            name="ck_narrative_voice_reference_audio",
        ),
    )
    op.create_index(
        "ix_narrative_voice_reference_project",
        "narrative_voice_references",
        ["project_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_narrative_voice_reference_project", table_name="narrative_voice_references")
    op.drop_table("narrative_voice_references")
