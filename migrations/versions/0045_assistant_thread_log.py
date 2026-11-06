"""Append-only assistant thread log, backfilled from existing conversations (ADR 0060).

Existing threads get the events they would have written: a new log with an empty past
would make the model forget every conversation already in progress. Backfilled events
are ordered by when they happened, then by a turn's natural order for ties.

Revision ID: 0045_assistant_thread_log
Revises: 0044_access_credits
"""

import sqlalchemy as sa
from alembic import op

revision = "0045_assistant_thread_log"
down_revision = "0044_access_credits"
branch_labels = None
depends_on = None

_BACKFILL = """
WITH happened AS (
    SELECT t.tenant_id, t.project_id, t.id AS thread_id, t.created_at AS at,
           0 AS turn_sequence, 0 AS rank, 'thread.created' AS kind,
           t.author_user_id AS actor,
           json_build_object('title', t.title) AS payload
    FROM narrative_assistant_threads t
    UNION ALL
    SELECT u.tenant_id, u.project_id, u.thread_id, u.created_at,
           u.sequence, 1, 'turn.requested', u.author_user_id,
           json_build_object(
               'turn_id', u.id, 'turn_sequence', u.sequence, 'request', u.request,
               'base_revision_id', u.base_revision_id, 'focus_node', u.focus_node
           )
    FROM narrative_assistant_turns u
    UNION ALL
    SELECT u.tenant_id, u.project_id, u.thread_id, COALESCE(u.finished_at, u.updated_at),
           u.sequence, 2, 'turn.' || u.status, NULL,
           CASE WHEN u.status = 'completed' THEN json_build_object(
               'turn_id', u.id, 'turn_sequence', u.sequence, 'reply', u.reply,
               'model', u.model, 'attempts', u.attempts,
               'input_tokens', u.input_tokens, 'output_tokens', u.output_tokens
           ) ELSE json_build_object(
               'turn_id', u.id, 'turn_sequence', u.sequence, 'error_code', u.error_code
           ) END
    FROM narrative_assistant_turns u
    WHERE u.status IN ('completed', 'failed', 'cancelled')
    UNION ALL
    SELECT p.tenant_id, p.project_id, p.thread_id, COALESCE(u.finished_at, p.created_at),
           u.sequence, 3, 'proposal.created', NULL,
           json_build_object(
               'proposal_id', p.id, 'turn_id', p.turn_id, 'summary', p.summary,
               'status', CASE WHEN json_array_length(p.diagnostics) > 0
                              THEN 'invalid' ELSE 'ready' END,
               'operations', json_array_length(p.operations)
           )
    FROM narrative_assistant_proposals p
    JOIN narrative_assistant_turns u ON u.id = p.turn_id
    UNION ALL
    SELECT p.tenant_id, p.project_id, p.thread_id, p.decided_at,
           u.sequence, 4, 'proposal.' || p.status, p.decided_by_user_id,
           json_build_object(
               'proposal_id', p.id, 'revision_id', p.accepted_revision_id,
               'summary', p.summary, 'conflicted', COALESCE(r.conflicted, false)
           )
    FROM narrative_assistant_proposals p
    JOIN narrative_assistant_turns u ON u.id = p.turn_id
    LEFT JOIN narrative_revisions r ON r.id = p.accepted_revision_id
    WHERE p.status IN ('accepted', 'rejected') AND p.decided_at IS NOT NULL
)
INSERT INTO narrative_assistant_thread_events
    (id, tenant_id, project_id, thread_id, sequence, kind, payload, actor_user_id, created_at)
SELECT gen_random_uuid(), tenant_id, project_id, thread_id,
       row_number() OVER (PARTITION BY thread_id ORDER BY at, turn_sequence, rank),
       kind, payload, actor, at
FROM happened
"""

_COUNTERS = """
UPDATE narrative_assistant_threads t
SET next_event_sequence = 1 + COALESCE(
    (SELECT max(e.sequence) FROM narrative_assistant_thread_events e WHERE e.thread_id = t.id), 0
)
"""

_REFUSE = """
CREATE FUNCTION narrative_thread_events_refuse_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'the assistant thread log is append-only; % was refused', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql
"""

_TRIGGER = """
CREATE TRIGGER narrative_thread_events_append_only
    BEFORE UPDATE OR DELETE ON narrative_assistant_thread_events
    FOR EACH ROW EXECUTE FUNCTION narrative_thread_events_refuse_mutation()
"""


def upgrade() -> None:
    op.add_column(
        "narrative_assistant_threads",
        sa.Column("next_event_sequence", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_table(
        "narrative_assistant_thread_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["thread_id", "project_id", "tenant_id"],
            [
                "narrative_assistant_threads.id",
                "narrative_assistant_threads.project_id",
                "narrative_assistant_threads.tenant_id",
            ],
            name="fk_narrative_assistant_thread_event_thread",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "thread_id", "sequence", name="uq_narrative_assistant_thread_event_sequence"
        ),
        sa.CheckConstraint("sequence > 0", name="ck_narrative_assistant_thread_event_sequence"),
    )
    op.execute(_BACKFILL)
    op.execute(_COUNTERS)
    op.execute(_REFUSE)
    op.execute(_TRIGGER)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER narrative_thread_events_append_only ON narrative_assistant_thread_events"
    )
    op.execute("DROP FUNCTION narrative_thread_events_refuse_mutation()")
    op.drop_table("narrative_assistant_thread_events")
    op.drop_column("narrative_assistant_threads", "next_event_sequence")
