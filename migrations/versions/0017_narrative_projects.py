"""Workspace narrative projects and immutable canonical source revisions.

Revision ID: 0017_narrative_projects
Revises: 0016_conversation_ledger
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_narrative_projects"
down_revision: str | None = "0016_conversation_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "narrative_projects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("creation_key", sa.Uuid(), nullable=False),
        sa.Column("creation_hash", sa.String(64), nullable=False),
        sa.Column("head_revision_id", sa.Uuid(), nullable=True),
        sa.Column("next_revision_number", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_narrative_projects_id_tenant"),
        sa.UniqueConstraint("tenant_id", "creation_key", name="uq_narrative_projects_creation_key"),
        sa.CheckConstraint("next_revision_number > 0", name="ck_narrative_project_sequence"),
    )
    op.create_index(
        "ix_narrative_projects_tenant_created",
        "narrative_projects",
        ["tenant_id", "created_at", "id"],
    )
    op.create_table(
        "narrative_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("parent_revision_id", sa.Uuid(), nullable=True),
        sa.Column("observed_head_revision_id", sa.Uuid(), nullable=True),
        sa.Column("conflicted", sa.Boolean(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("story_json", sa.Text(), nullable=False),
        sa.Column("notices", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["narrative_projects.id", "narrative_projects.tenant_id"],
            name="fk_narrative_revision_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_revision_id", "project_id", "tenant_id"],
            [
                "narrative_revisions.id",
                "narrative_revisions.project_id",
                "narrative_revisions.tenant_id",
            ],
            name="fk_narrative_revision_parent",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["observed_head_revision_id", "project_id", "tenant_id"],
            [
                "narrative_revisions.id",
                "narrative_revisions.project_id",
                "narrative_revisions.tenant_id",
            ],
            name="fk_narrative_revision_observed",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("id", "project_id", "tenant_id", name="uq_narrative_revision_scope"),
        sa.UniqueConstraint("project_id", "revision_number", name="uq_narrative_revision_number"),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_narrative_revision_key"),
        sa.CheckConstraint("revision_number > 0", name="ck_narrative_revision_sequence"),
    )
    op.create_foreign_key(
        "fk_narrative_project_head",
        "narrative_projects",
        "narrative_revisions",
        ["head_revision_id", "id", "tenant_id"],
        ["id", "project_id", "tenant_id"],
        ondelete="RESTRICT",
    )
    op.execute("""
        CREATE FUNCTION narrative_revision_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Narrative revisions are immutable' USING ERRCODE = '55000';
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER narrative_revision_immutable
        BEFORE UPDATE OR DELETE ON narrative_revisions
        FOR EACH ROW EXECUTE FUNCTION narrative_revision_immutable()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER narrative_revision_immutable ON narrative_revisions")
    op.execute("DROP FUNCTION narrative_revision_immutable()")
    op.drop_constraint("fk_narrative_project_head", "narrative_projects", type_="foreignkey")
    op.drop_table("narrative_revisions")
    op.drop_index("ix_narrative_projects_tenant_created", table_name="narrative_projects")
    op.drop_table("narrative_projects")
