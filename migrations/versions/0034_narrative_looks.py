"""Private reviewed looks and advisory image feedback.
Revision ID: 0034_narrative_looks
Revises: 0033_prompt_bundles
"""

import sqlalchemy as sa
from alembic import op

revision = "0034_narrative_looks"
down_revision = "0033_prompt_bundles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "narrative_character_looks",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("character_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("identity_tags", sa.JSON(), nullable=False),
        sa.Column("clothing_tags", sa.JSON(), nullable=False),
        sa.Column("character_type", sa.String(length=16), nullable=False),
        sa.Column("parent_look_id", sa.Uuid(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("creation_key", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("tagger_observation", sa.JSON(), nullable=True),
        sa.Column("prompt_bundle_sha256", sa.String(length=64), nullable=False),
        sa.Column("policy_sha256", sa.String(length=64), nullable=False),
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
        sa.CheckConstraint("length(name) BETWEEN 1 AND 80", name="ck_character_look_name"),
        sa.ForeignKeyConstraint(
            ["asset_id", "project_id", "tenant_id"],
            ["narrative_assets.id", "narrative_assets.project_id", "narrative_assets.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_look_id", "project_id", "tenant_id", "character_id"],
            [
                "narrative_character_looks.id",
                "narrative_character_looks.project_id",
                "narrative_character_looks.tenant_id",
                "narrative_character_looks.character_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["narrative_projects.id", "narrative_projects.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_bundle_sha256"], ["prompt_bundles.sha256"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "project_id", "tenant_id", "character_id", name="uq_character_look_scope"
        ),
        sa.UniqueConstraint("project_id", "creation_key", name="uq_character_look_key"),
    )
    op.create_index(
        "ix_character_look_project",
        "narrative_character_looks",
        ["tenant_id", "project_id", "character_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "narrative_look_selections",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("character_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("look_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
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
        sa.CheckConstraint("version > 0", name="ck_look_selection_version"),
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
        sa.ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["narrative_projects.id", "narrative_projects.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("project_id", "character_id"),
    )
    op.create_table(
        "narrative_look_jobs",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("character_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("look_id", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
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
        sa.PrimaryKeyConstraint("job_id", "character_id"),
    )
    op.create_index(
        "ix_look_jobs_character",
        "narrative_look_jobs",
        ["tenant_id", "project_id", "character_id"],
        unique=False,
    )
    op.create_table(
        "narrative_candidate_reviews",
        sa.Column("look_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("character_id", sa.String(length=64), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("candidate_sha256", sa.String(length=64), nullable=False),
        sa.Column("identity", sa.String(length=16), nullable=False),
        sa.Column("clothes", sa.String(length=16), nullable=False),
        sa.Column("notes", sa.String(length=1200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=False),
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
            "identity IN ('same','drifted','unknown') AND clothes IN ('same','drifted','unknown')",
            name="ck_candidate_review_labels",
        ),
        sa.CheckConstraint("version > 0", name="ck_candidate_review_version"),
        sa.ForeignKeyConstraint(
            ["asset_id", "project_id", "tenant_id"],
            ["narrative_assets.id", "narrative_assets.project_id", "narrative_assets.tenant_id"],
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
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("look_id", "asset_id"),
    )
    op.create_index(
        "ix_candidate_reviews_assets",
        "narrative_candidate_reviews",
        ["tenant_id", "project_id", "asset_id"],
        unique=False,
    )
    op.create_table(
        "narrative_look_observations",
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("tagger_sha256", sa.String(length=64), nullable=False),
        sa.Column("observation", sa.JSON(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["asset_id", "project_id", "tenant_id"],
            ["narrative_assets.id", "narrative_assets.project_id", "narrative_assets.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "asset_id", "source_sha256", "tagger_sha256", name="uq_look_observation_source"
        ),
    )


def downgrade() -> None:
    op.drop_table("narrative_look_observations")
    op.drop_table("narrative_candidate_reviews")
    op.drop_table("narrative_look_jobs")
    op.drop_table("narrative_look_selections")
    op.drop_table("narrative_character_looks")
