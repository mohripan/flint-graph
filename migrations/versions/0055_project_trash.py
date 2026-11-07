"""Deleting a project forever: when it began, and the one way past the immutable tables (ADR 0073).

Revisions, releases and the assistant's log refuse updates and deletes. They still do, except for
a delete of rows whose own project has begun being deleted forever.

Revision ID: 0055_project_trash
Revises: 0054_narrative_gpu_sessions
"""

import sqlalchemy as sa
from alembic import op

revision = "0055_project_trash"
down_revision = "0054_narrative_gpu_sessions"
branch_labels = None
depends_on = None

_PURGING = """
    IF TG_OP = 'DELETE' AND EXISTS (
        SELECT 1 FROM narrative_projects
        WHERE id = OLD.project_id AND purge_started_at IS NOT NULL
    ) THEN
        RETURN OLD;
    END IF;
"""


def _function(name: str, raising: str, purge: str = "") -> str:
    return f"""
    CREATE OR REPLACE FUNCTION {name}() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
    {purge}
        {raising}
    END;
    $$
    """


_REVISIONS = "RAISE EXCEPTION 'Narrative revisions are immutable' USING ERRCODE = '55000';"
_RELEASES = "RAISE EXCEPTION 'Narrative release records are immutable' USING ERRCODE = '55000';"
_THREAD_LOG = (
    "RAISE EXCEPTION 'the assistant thread log is append-only; % was refused', TG_OP "
    "USING ERRCODE = 'restrict_violation';"
)


def upgrade() -> None:
    op.add_column(
        "narrative_projects",
        sa.Column("purge_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(_function("narrative_revision_immutable", _REVISIONS, _PURGING))
    op.execute(_function("narrative_release_immutable", _RELEASES, _PURGING))
    op.execute(_function("narrative_thread_events_refuse_mutation", _THREAD_LOG, _PURGING))


def downgrade() -> None:
    op.execute(_function("narrative_thread_events_refuse_mutation", _THREAD_LOG))
    op.execute(_function("narrative_release_immutable", _RELEASES))
    op.execute(_function("narrative_revision_immutable", _REVISIONS))
    op.drop_column("narrative_projects", "purge_started_at")
