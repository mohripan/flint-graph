"""Screenshots attached to a message to the assistant (ADR 0076).

Revision ID: 0058_assistant_images
Revises: 0057_own_server_is_unlimited
"""

import sqlalchemy as sa
from alembic import op

revision = "0058_assistant_images"
down_revision = "0057_own_server_is_unlimited"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "narrative_assistant_images",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["narrative_projects.id", "narrative_projects.tenant_id"],
            name="fk_narrative_assistant_image_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("project_id", "sha256", name="uq_narrative_assistant_image_sha"),
    )


def downgrade() -> None:
    op.drop_table("narrative_assistant_images")
