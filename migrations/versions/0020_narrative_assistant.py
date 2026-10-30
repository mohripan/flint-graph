"""Project assistant threads, fenced turns and reviewable proposals (ADR 0038).

Revision ID: 0020_narrative_assistant
Revises: 0019_narrative_workflow_owner
"""

import sqlalchemy as sa
from alembic import op

revision = "0020_narrative_assistant"
down_revision = "0019_narrative_workflow_owner"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def _revision_fk(column: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column, "project_id", "tenant_id"],
        [
            "narrative_revisions.id",
            "narrative_revisions.project_id",
            "narrative_revisions.tenant_id",
        ],
        name=name,
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.create_table(
        "narrative_assistant_threads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("creation_key", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("next_sequence", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["narrative_projects.id", "narrative_projects.tenant_id"],
            name="fk_narrative_assistant_thread_project",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "id", "project_id", "tenant_id", name="uq_narrative_assistant_thread_scope"
        ),
        sa.UniqueConstraint("project_id", "creation_key", name="uq_narrative_assistant_thread_key"),
        sa.CheckConstraint("next_sequence > 0", name="ck_narrative_assistant_thread_sequence"),
    )
    op.create_index(
        "ix_narrative_assistant_threads_project",
        "narrative_assistant_threads",
        ["project_id", "updated_at", "id"],
    )
    op.create_table(
        "narrative_assistant_turns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=False),
        sa.Column("request", sa.Text(), nullable=False),
        sa.Column("base_revision_id", sa.Uuid(), nullable=False),
        sa.Column("focus_node", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("execution_token", sa.Uuid(), nullable=True),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=True),
        sa.Column("activity_attempt", sa.Integer(), nullable=True),
        sa.Column("reply", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("prompt_sha256", sa.String(length=64), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["thread_id", "project_id", "tenant_id"],
            [
                "narrative_assistant_threads.id",
                "narrative_assistant_threads.project_id",
                "narrative_assistant_threads.tenant_id",
            ],
            name="fk_narrative_assistant_turn_thread",
            ondelete="RESTRICT",
        ),
        _revision_fk("base_revision_id", "fk_narrative_assistant_turn_base"),
        sa.UniqueConstraint(
            "id", "thread_id", "project_id", "tenant_id", name="uq_narrative_assistant_turn_scope"
        ),
        sa.UniqueConstraint("thread_id", "sequence", name="uq_narrative_assistant_turn_sequence"),
        sa.UniqueConstraint("thread_id", "idempotency_key", name="uq_narrative_assistant_turn_key"),
        sa.CheckConstraint("sequence > 0", name="ck_narrative_assistant_turn_sequence"),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','failed','cancelled')",
            name="ck_narrative_assistant_turn_status",
        ),
        sa.CheckConstraint(
            "(status = 'running' AND execution_token IS NOT NULL) OR "
            "(status <> 'running' AND execution_token IS NULL)",
            name="ck_narrative_assistant_turn_execution_fence",
        ),
        sa.CheckConstraint(
            "status <> 'completed' OR NOT cancel_requested",
            name="ck_narrative_assistant_turn_not_cancelled_completed",
        ),
        sa.CheckConstraint(
            "(workflow_run_id IS NULL AND activity_attempt IS NULL) OR "
            "(workflow_run_id IS NOT NULL AND activity_attempt IS NOT NULL "
            "AND activity_attempt >= 0)",
            name="ck_narrative_assistant_turn_workflow_owner",
        ),
    )
    op.create_index(
        "ix_narrative_assistant_turn_active",
        "narrative_assistant_turns",
        ["tenant_id"],
        postgresql_where=sa.text("status IN ('queued','running')"),
    )
    op.create_index(
        "ix_narrative_assistant_turn_run_status",
        "narrative_assistant_turns",
        ["status", "workflow_run_id"],
    )
    op.create_table(
        "narrative_assistant_proposals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("turn_id", sa.Uuid(), nullable=False),
        sa.Column("base_revision_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("summary", sa.String(length=400), nullable=False),
        sa.Column("operations", sa.JSON(), nullable=False),
        sa.Column("diagnostics", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("touched", sa.JSON(), nullable=False),
        sa.Column("accepted_revision_id", sa.Uuid(), nullable=True),
        sa.Column("decision_key", sa.Uuid(), nullable=True),
        sa.Column("decided_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["turn_id", "thread_id", "project_id", "tenant_id"],
            [
                "narrative_assistant_turns.id",
                "narrative_assistant_turns.thread_id",
                "narrative_assistant_turns.project_id",
                "narrative_assistant_turns.tenant_id",
            ],
            name="fk_narrative_assistant_proposal_turn",
            ondelete="RESTRICT",
        ),
        _revision_fk("base_revision_id", "fk_narrative_assistant_proposal_base"),
        _revision_fk("accepted_revision_id", "fk_narrative_assistant_proposal_accepted"),
        sa.UniqueConstraint("turn_id", name="uq_narrative_assistant_proposal_turn"),
        sa.CheckConstraint(
            "status IN ('ready','invalid','accepted','rejected')",
            name="ck_narrative_assistant_proposal_status",
        ),
        sa.CheckConstraint(
            "(status = 'accepted') = (accepted_revision_id IS NOT NULL)",
            name="ck_narrative_assistant_proposal_accepted",
        ),
    )


def downgrade() -> None:
    op.drop_table("narrative_assistant_proposals")
    op.drop_index("ix_narrative_assistant_turn_run_status", table_name="narrative_assistant_turns")
    op.drop_index("ix_narrative_assistant_turn_active", table_name="narrative_assistant_turns")
    op.drop_table("narrative_assistant_turns")
    op.drop_index(
        "ix_narrative_assistant_threads_project", table_name="narrative_assistant_threads"
    )
    op.drop_table("narrative_assistant_threads")
