"""identity and workspace memberships

Revision ID: 0014_identity_memberships
Revises: 0013_document_deleted_at
Create Date: 2026-07-22 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_identity_memberships"
down_revision: str | None = "0013_document_deleted_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

workspace_role = sa.Enum(
    "owner",
    "admin",
    "member",
    "viewer",
    name="workspace_role",
    native_enum=False,
    length=32,
)
workspace_membership_status = sa.Enum(
    "active",
    "disabled",
    name="workspace_membership_status",
    native_enum=False,
    length=32,
)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("oidc_issuer", sa.String(length=500), nullable=False),
        sa.Column("oidc_subject", sa.String(length=500), nullable=False),
        sa.Column("email", sa.String(length=500), nullable=True),
        sa.Column("display_name", sa.String(length=500), nullable=True),
        sa.Column("claims", sa.JSON(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("oidc_issuer", "oidc_subject", name="uq_users_oidc_identity"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "workspace_memberships",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", workspace_role, nullable=False),
        sa.Column("status", workspace_membership_status, nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_workspace_memberships_tenant_user"),
    )
    op.create_index(
        "ix_workspace_memberships_user_status",
        "workspace_memberships",
        ["user_id", "status"],
    )
    op.create_index(
        "ix_workspace_memberships_tenant_role",
        "workspace_memberships",
        ["tenant_id", "role"],
    )


def downgrade() -> None:
    op.drop_index("ix_workspace_memberships_tenant_role", table_name="workspace_memberships")
    op.drop_index("ix_workspace_memberships_user_status", table_name="workspace_memberships")
    op.drop_table("workspace_memberships")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
