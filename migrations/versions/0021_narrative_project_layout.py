"""Editor-only nested scene hierarchy per narrative project.

Revision ID: 0021_narrative_project_layout
Revises: 0020_narrative_assistant
"""

import sqlalchemy as sa
from alembic import op

revision = "0021_narrative_project_layout"
down_revision = "0020_narrative_assistant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "narrative_project_layouts",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=False),
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
        sa.PrimaryKeyConstraint("project_id"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["narrative_projects.id", "narrative_projects.tenant_id"],
            name="fk_narrative_project_layout_project",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("version > 0", name="ck_narrative_project_layout_version"),
    )


def downgrade() -> None:
    op.drop_table("narrative_project_layouts")
