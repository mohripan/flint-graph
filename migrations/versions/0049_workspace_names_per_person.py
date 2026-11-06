"""Workspace names are unique per person, not across the server.

A second person could not use a name someone already had, and the refusal revealed that the name
existed. `create_workspace_for_user` now enforces uniqueness among a person's own workspaces.

Downgrading fails if two workspaces have come to share a name.

Revision ID: 0049_workspace_names_per_person
Revises: 0048_assistant_child_sessions
"""

from alembic import op

revision = "0049_workspace_names_per_person"
down_revision = "0048_assistant_child_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("tenants_name_key", "tenants", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint("tenants_name_key", "tenants", ["name"])
