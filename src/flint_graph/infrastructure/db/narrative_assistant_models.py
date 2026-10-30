"""Project-scoped assistant threads, fenced turns and reviewable proposals (ADR 0038)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from flint_graph.infrastructure.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class NarrativeAssistantThread(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "narrative_assistant_threads"
    __table_args__ = (
        UniqueConstraint(
            "id", "project_id", "tenant_id", name="uq_narrative_assistant_thread_scope"
        ),
        UniqueConstraint("project_id", "creation_key", name="uq_narrative_assistant_thread_key"),
        ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["narrative_projects.id", "narrative_projects.tenant_id"],
            name="fk_narrative_assistant_thread_project",
            ondelete="RESTRICT",
        ),
        CheckConstraint("next_sequence > 0", name="ck_narrative_assistant_thread_sequence"),
        Index("ix_narrative_assistant_threads_project", "project_id", "updated_at", "id"),
    )
    tenant_id: Mapped[UUID]
    project_id: Mapped[UUID]
    author_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    title: Mapped[str] = mapped_column(String(200))
    creation_key: Mapped[UUID]
    request_hash: Mapped[str] = mapped_column(String(64))
    next_sequence: Mapped[int] = mapped_column(Integer, default=1)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NarrativeAssistantTurn(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One creator request and the assistant's durable reply job."""

    __tablename__ = "narrative_assistant_turns"
    __table_args__ = (
        UniqueConstraint(
            "id", "thread_id", "project_id", "tenant_id", name="uq_narrative_assistant_turn_scope"
        ),
        UniqueConstraint("thread_id", "sequence", name="uq_narrative_assistant_turn_sequence"),
        UniqueConstraint("thread_id", "idempotency_key", name="uq_narrative_assistant_turn_key"),
        ForeignKeyConstraint(
            ["thread_id", "project_id", "tenant_id"],
            [
                "narrative_assistant_threads.id",
                "narrative_assistant_threads.project_id",
                "narrative_assistant_threads.tenant_id",
            ],
            name="fk_narrative_assistant_turn_thread",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["base_revision_id", "project_id", "tenant_id"],
            [
                "narrative_revisions.id",
                "narrative_revisions.project_id",
                "narrative_revisions.tenant_id",
            ],
            name="fk_narrative_assistant_turn_base",
            ondelete="RESTRICT",
        ),
        CheckConstraint("sequence > 0", name="ck_narrative_assistant_turn_sequence"),
        CheckConstraint(
            "status IN ('queued','running','completed','failed','cancelled')",
            name="ck_narrative_assistant_turn_status",
        ),
        CheckConstraint(
            "(status = 'running' AND execution_token IS NOT NULL) OR "
            "(status <> 'running' AND execution_token IS NULL)",
            name="ck_narrative_assistant_turn_execution_fence",
        ),
        CheckConstraint(
            "status <> 'completed' OR NOT cancel_requested",
            name="ck_narrative_assistant_turn_not_cancelled_completed",
        ),
        CheckConstraint(
            "(workflow_run_id IS NULL AND activity_attempt IS NULL) OR "
            "(workflow_run_id IS NOT NULL AND activity_attempt IS NOT NULL "
            "AND activity_attempt >= 0)",
            name="ck_narrative_assistant_turn_workflow_owner",
        ),
        Index(
            "ix_narrative_assistant_turn_active",
            "tenant_id",
            postgresql_where=text("status IN ('queued','running')"),
            sqlite_where=text("status IN ('queued','running')"),
        ),
        Index("ix_narrative_assistant_turn_run_status", "status", "workflow_run_id"),
    )
    tenant_id: Mapped[UUID]
    project_id: Mapped[UUID]
    thread_id: Mapped[UUID]
    sequence: Mapped[int] = mapped_column(Integer)
    author_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    request: Mapped[str] = mapped_column(Text)
    base_revision_id: Mapped[UUID]
    focus_node: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[UUID]
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    execution_token: Mapped[UUID | None]
    workflow_run_id: Mapped[UUID | None]
    activity_attempt: Mapped[int | None]
    reply: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(80))
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(200))
    prompt_sha256: Mapped[str | None] = mapped_column(String(64))
    attempts: Mapped[int | None]
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NarrativeAssistantProposal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Bounded story edits from one turn; canon only through explicit acceptance."""

    __tablename__ = "narrative_assistant_proposals"
    __table_args__ = (
        UniqueConstraint("turn_id", name="uq_narrative_assistant_proposal_turn"),
        ForeignKeyConstraint(
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
        ForeignKeyConstraint(
            ["base_revision_id", "project_id", "tenant_id"],
            [
                "narrative_revisions.id",
                "narrative_revisions.project_id",
                "narrative_revisions.tenant_id",
            ],
            name="fk_narrative_assistant_proposal_base",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["accepted_revision_id", "project_id", "tenant_id"],
            [
                "narrative_revisions.id",
                "narrative_revisions.project_id",
                "narrative_revisions.tenant_id",
            ],
            name="fk_narrative_assistant_proposal_accepted",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('ready','invalid','accepted','rejected')",
            name="ck_narrative_assistant_proposal_status",
        ),
        CheckConstraint(
            "(status = 'accepted') = (accepted_revision_id IS NOT NULL)",
            name="ck_narrative_assistant_proposal_accepted",
        ),
    )
    tenant_id: Mapped[UUID]
    project_id: Mapped[UUID]
    thread_id: Mapped[UUID]
    turn_id: Mapped[UUID]
    base_revision_id: Mapped[UUID]
    status: Mapped[str] = mapped_column(String(16))
    summary: Mapped[str] = mapped_column(String(400))
    operations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    diagnostics: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    warnings: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    touched: Mapped[list[str]] = mapped_column(JSON, default=list)
    accepted_revision_id: Mapped[UUID | None]
    decision_key: Mapped[UUID | None]
    decided_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
