"""Project asset library: uploads, kinds, rights declarations and background jobs (ADR 0040).

Revision ID: 0024_narrative_asset_library
Revises: 0023_narrative_turn_events
"""

import sqlalchemy as sa
from alembic import op

revision = "0024_narrative_asset_library"
down_revision = "0023_narrative_turn_events"
branch_labels = None
depends_on = None

KINDS = "kind IN ('character_portrait','background','sprite','image','font')"
MEDIA = "media_type IN ('image/png','font/ttf','font/otf')"
SHAPE = (
    "size_bytes > 0 AND ((media_type = 'image/png' AND width > 0 AND height > 0) "
    "OR (media_type <> 'image/png' AND width IS NULL AND height IS NULL))"
)


def upgrade() -> None:
    op.add_column(
        "narrative_assets",
        sa.Column("name", sa.String(length=120), nullable=False, server_default="Image"),
    )
    op.alter_column("narrative_assets", "name", server_default=None)
    op.add_column("narrative_assets", sa.Column("notice", sa.Text(), nullable=True))
    op.add_column(
        "narrative_assets", sa.Column("rights_declared_by_user_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "narrative_assets",
        sa.Column("rights_declared_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_narrative_asset_rights_user",
        "narrative_assets",
        "users",
        ["rights_declared_by_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    for column in (
        "width",
        "height",
        "thumbnail_sha256",
        "thumbnail_size_bytes",
        "thumbnail_width",
        "thumbnail_height",
    ):
        op.alter_column("narrative_assets", column, nullable=True)
    for name in (
        "ck_narrative_asset_kind",
        "ck_narrative_asset_media_type",
        "ck_narrative_asset_shape",
    ):
        op.drop_constraint(name, "narrative_assets", type_="check")
    op.create_check_constraint("ck_narrative_asset_kind", "narrative_assets", KINDS)
    op.create_check_constraint("ck_narrative_asset_media_type", "narrative_assets", MEDIA)
    op.create_check_constraint("ck_narrative_asset_shape", "narrative_assets", SHAPE)
    op.create_check_constraint(
        "ck_narrative_asset_source", "narrative_assets", "source IN ('generated','uploaded')"
    )
    op.create_check_constraint(
        "ck_narrative_asset_rights",
        "narrative_assets",
        "source <> 'uploaded' OR (rights_declared_at IS NOT NULL "
        "AND rights_declared_by_user_id IS NOT NULL)",
    )
    op.create_index(
        "ix_narrative_assets_project_kind", "narrative_assets", ["project_id", "kind", "created_at"]
    )
    op.create_index(
        "uq_narrative_asset_project_sha",
        "narrative_assets",
        ["tenant_id", "project_id", "sha256"],
        unique=True,
        postgresql_where=sa.text("status <> 'discarded'"),
    )
    op.alter_column("narrative_image_jobs", "character_id", nullable=True)
    op.create_check_constraint(
        "ck_narrative_image_job_purpose",
        "narrative_image_jobs",
        "(purpose = 'character_portrait' AND character_id IS NOT NULL) "
        "OR (purpose = 'background' AND character_id IS NULL)",
    )
    op.create_index(
        "ix_narrative_image_job_purpose",
        "narrative_image_jobs",
        ["project_id", "purpose", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_narrative_image_job_purpose", table_name="narrative_image_jobs")
    op.drop_constraint("ck_narrative_image_job_purpose", "narrative_image_jobs", type_="check")
    op.execute("DELETE FROM narrative_assets WHERE kind NOT IN ('character_portrait')")
    op.execute("DELETE FROM narrative_image_jobs WHERE character_id IS NULL")
    op.alter_column("narrative_image_jobs", "character_id", nullable=False)
    op.drop_index("uq_narrative_asset_project_sha", table_name="narrative_assets")
    op.drop_index("ix_narrative_assets_project_kind", table_name="narrative_assets")
    for name in (
        "ck_narrative_asset_rights",
        "ck_narrative_asset_source",
        "ck_narrative_asset_shape",
        "ck_narrative_asset_media_type",
        "ck_narrative_asset_kind",
    ):
        op.drop_constraint(name, "narrative_assets", type_="check")
    op.create_check_constraint(
        "ck_narrative_asset_kind", "narrative_assets", "kind IN ('character_portrait')"
    )
    op.create_check_constraint(
        "ck_narrative_asset_media_type", "narrative_assets", "media_type = 'image/png'"
    )
    op.create_check_constraint(
        "ck_narrative_asset_shape",
        "narrative_assets",
        "size_bytes > 0 AND width > 0 AND height > 0",
    )
    for column in (
        "width",
        "height",
        "thumbnail_sha256",
        "thumbnail_size_bytes",
        "thumbnail_width",
        "thumbnail_height",
    ):
        op.alter_column("narrative_assets", column, nullable=False)
    op.drop_constraint("fk_narrative_asset_rights_user", "narrative_assets", type_="foreignkey")
    for column in ("rights_declared_at", "rights_declared_by_user_id", "notice", "name"):
        op.drop_column("narrative_assets", column)
