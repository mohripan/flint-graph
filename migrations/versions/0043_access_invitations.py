"""Invite-only access: invitations, grants and usage charges (ADR 0058).

Revision ID: 0043_access_invitations
Revises: 0042_pose_guides
"""

import sqlalchemy as sa
from alembic import op

revision = "0043_access_invitations"
down_revision = "0042_pose_guides"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "access_invitations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("key_sha256", sa.String(64), nullable=True),
        sa.Column("key_hint", sa.String(4), nullable=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("max_redemptions", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("redemption_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("limits", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("kind IN ('key', 'email')", name="ck_access_invitations_kind"),
        sa.CheckConstraint(
            "(kind = 'key' AND key_sha256 IS NOT NULL AND email IS NULL)"
            " OR (kind = 'email' AND email IS NOT NULL AND key_sha256 IS NULL)",
            name="ck_access_invitations_target",
        ),
        sa.CheckConstraint(
            "max_redemptions >= 1 AND redemption_count >= 0"
            " AND redemption_count <= max_redemptions",
            name="ck_access_invitations_redemptions",
        ),
        sa.UniqueConstraint("key_sha256", name="uq_access_invitations_key"),
    )
    op.create_index("ix_access_invitations_email", "access_invitations", ["email"])
    op.create_table(
        "access_grants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("invitation_id", sa.Uuid(), nullable=True),
        sa.Column("limits", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="active"),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invitation_id"], ["access_invitations.id"], ondelete="SET NULL"),
        sa.CheckConstraint("status IN ('active', 'suspended')", name="ck_access_grants_status"),
        sa.UniqueConstraint("user_id", name="uq_access_grants_user"),
    )
    op.create_table(
        "usage_charges",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "kind IN ('image', 'voice', 'assistant', 'release', 'training')",
            name="ck_usage_charges_kind",
        ),
        sa.CheckConstraint("units > 0", name="ck_usage_charges_units"),
    )
    op.create_index(
        "ix_usage_charges_user_kind_time", "usage_charges", ["user_id", "kind", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_usage_charges_user_kind_time", table_name="usage_charges")
    op.drop_table("usage_charges")
    op.drop_table("access_grants")
    op.drop_index("ix_access_invitations_email", table_name="access_invitations")
    op.drop_table("access_invitations")
