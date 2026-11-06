"""Durable generation actions of assistant proposals, and automatic generation (ADR 0061).

Existing proposals get no rows: their actions read as offered, and any job already started
for them is still found by its derived key. Existing turns stay on manual generation.

Revision ID: 0046_assistant_actions
Revises: 0045_assistant_thread_log
"""

import sqlalchemy as sa
from alembic import op

revision = "0046_assistant_actions"
down_revision = "0045_assistant_thread_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "narrative_assistant_turns",
        sa.Column("auto_generate", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "narrative_assistant_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("op_index", sa.Integer(), nullable=False),
        sa.Column("op", sa.String(length=40), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("image_job_id", sa.Uuid(), nullable=True),
        sa.Column("voice_job_id", sa.Uuid(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("detail", sa.String(length=300), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("proposal_id", "op_index", name="uq_narrative_assistant_action_op"),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["narrative_assistant_proposals.id"],
            name="fk_narrative_assistant_action_proposal",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["thread_id", "project_id", "tenant_id"],
            [
                "narrative_assistant_threads.id",
                "narrative_assistant_threads.project_id",
                "narrative_assistant_threads.tenant_id",
            ],
            name="fk_narrative_assistant_action_thread",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["image_job_id"],
            ["narrative_image_jobs.id"],
            name="fk_narrative_assistant_action_image_job",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["voice_job_id"],
            ["narrative_voice_jobs.id"],
            name="fk_narrative_assistant_action_voice_job",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('offered','waiting','pending','started','blocked','finished','skipped')",
            name="ck_narrative_assistant_action_status",
        ),
        sa.CheckConstraint(
            "image_job_id IS NULL OR voice_job_id IS NULL",
            name="ck_narrative_assistant_action_one_job",
        ),
    )
    op.create_index(
        "ix_narrative_assistant_action_open",
        "narrative_assistant_actions",
        ["status", "created_at"],
        postgresql_where=sa.text("status IN ('pending','started')"),
    )
    op.create_index(
        "ix_narrative_assistant_action_image_job",
        "narrative_assistant_actions",
        ["image_job_id"],
        postgresql_where=sa.text("image_job_id IS NOT NULL"),
    )
    op.create_index(
        "ix_narrative_assistant_action_voice_job",
        "narrative_assistant_actions",
        ["voice_job_id"],
        postgresql_where=sa.text("voice_job_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_table("narrative_assistant_actions")
    op.drop_column("narrative_assistant_turns", "auto_generate")
