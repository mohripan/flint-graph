"""Child sessions: conversations under a parent conversation (ADR 0063).

Existing conversations stay roots, made by a creator.

Revision ID: 0048_assistant_child_sessions
Revises: 0047_assistant_attachments
"""

import sqlalchemy as sa
from alembic import op

revision = "0048_assistant_child_sessions"
down_revision = "0047_assistant_attachments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "narrative_assistant_threads", sa.Column("parent_thread_id", sa.Uuid(), nullable=True)
    )
    op.add_column("narrative_assistant_threads", sa.Column("task", sa.Text(), nullable=True))
    op.add_column(
        "narrative_assistant_threads",
        sa.Column("origin", sa.String(length=16), nullable=False, server_default="creator"),
    )
    op.create_foreign_key(
        "fk_narrative_assistant_thread_parent",
        "narrative_assistant_threads",
        "narrative_assistant_threads",
        ["parent_thread_id", "project_id", "tenant_id"],
        ["id", "project_id", "tenant_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_narrative_assistant_thread_parent",
        "narrative_assistant_threads",
        "parent_thread_id IS NULL OR parent_thread_id <> id",
    )
    op.create_check_constraint(
        "ck_narrative_assistant_thread_origin",
        "narrative_assistant_threads",
        "origin IN ('creator','assistant')",
    )
    op.create_index(
        "ix_narrative_assistant_threads_parent",
        "narrative_assistant_threads",
        ["parent_thread_id", "created_at"],
        postgresql_where=sa.text("parent_thread_id IS NOT NULL"),
    )
    op.add_column(
        "narrative_assistant_actions", sa.Column("child_thread_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        "fk_narrative_assistant_action_child",
        "narrative_assistant_actions",
        "narrative_assistant_threads",
        ["child_thread_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "ck_narrative_assistant_action_one_job", "narrative_assistant_actions", type_="check"
    )
    op.create_check_constraint(
        "ck_narrative_assistant_action_one_job",
        "narrative_assistant_actions",
        "(CASE WHEN image_job_id IS NOT NULL THEN 1 ELSE 0 END) "
        "+ (CASE WHEN voice_job_id IS NOT NULL THEN 1 ELSE 0 END) "
        "+ (CASE WHEN child_thread_id IS NOT NULL THEN 1 ELSE 0 END) <= 1",
    )
    op.create_index(
        "ix_narrative_assistant_action_child",
        "narrative_assistant_actions",
        ["child_thread_id"],
        postgresql_where=sa.text("child_thread_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_narrative_assistant_action_child", table_name="narrative_assistant_actions")
    op.drop_constraint(
        "ck_narrative_assistant_action_one_job", "narrative_assistant_actions", type_="check"
    )
    op.create_check_constraint(
        "ck_narrative_assistant_action_one_job",
        "narrative_assistant_actions",
        "image_job_id IS NULL OR voice_job_id IS NULL",
    )
    op.drop_constraint(
        "fk_narrative_assistant_action_child", "narrative_assistant_actions", type_="foreignkey"
    )
    op.drop_column("narrative_assistant_actions", "child_thread_id")
    op.drop_index("ix_narrative_assistant_threads_parent", table_name="narrative_assistant_threads")
    op.drop_constraint(
        "ck_narrative_assistant_thread_origin", "narrative_assistant_threads", type_="check"
    )
    op.drop_constraint(
        "ck_narrative_assistant_thread_parent", "narrative_assistant_threads", type_="check"
    )
    op.drop_constraint(
        "fk_narrative_assistant_thread_parent", "narrative_assistant_threads", type_="foreignkey"
    )
    op.drop_column("narrative_assistant_threads", "origin")
    op.drop_column("narrative_assistant_threads", "task")
    op.drop_column("narrative_assistant_threads", "parent_thread_id")
