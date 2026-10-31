"""Asset folders: editor-only organization of a project's library (ADR 0043).

Revision ID: 0028_narrative_asset_folders
Revises: 0027_narrative_image_hires
"""

import sqlalchemy as sa
from alembic import op

revision = "0028_narrative_asset_folders"
down_revision = "0027_narrative_image_hires"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "narrative_asset_folders",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        *(
            sa.Column(
                name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
            )
            for name in ("created_at", "updated_at")
        ),
        sa.UniqueConstraint(
            "id", "project_id", "tenant_id", name="uq_narrative_asset_folder_scope"
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["narrative_projects.id", "narrative_projects.tenant_id"],
            name="fk_narrative_asset_folder_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id", "project_id", "tenant_id"],
            [
                "narrative_asset_folders.id",
                "narrative_asset_folders.project_id",
                "narrative_asset_folders.tenant_id",
            ],
            name="fk_narrative_asset_folder_parent",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], name="fk_narrative_asset_folder_user"
        ),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 80", name="ck_narrative_asset_folder_name"),
        sa.CheckConstraint(
            "parent_id IS NULL OR parent_id <> id", name="ck_narrative_asset_folder_self"
        ),
    )
    op.create_index(
        "ix_narrative_asset_folders_project", "narrative_asset_folders", ["project_id", "parent_id"]
    )
    op.add_column("narrative_assets", sa.Column("folder_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_narrative_asset_folder",
        "narrative_assets",
        "narrative_asset_folders",
        ["folder_id", "project_id", "tenant_id"],
        ["id", "project_id", "tenant_id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_narrative_assets_folder", "narrative_assets", ["project_id", "folder_id"])


def downgrade() -> None:
    op.drop_index("ix_narrative_assets_folder", table_name="narrative_assets")
    op.drop_constraint("fk_narrative_asset_folder", "narrative_assets", type_="foreignkey")
    op.drop_column("narrative_assets", "folder_id")
    op.drop_index("ix_narrative_asset_folders_project", table_name="narrative_asset_folders")
    op.drop_table("narrative_asset_folders")
