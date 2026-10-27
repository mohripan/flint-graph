"""Workspace-owned narrative editing containers and immutable source snapshots."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
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
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from flint_graph.infrastructure.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class NarrativeProject(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "narrative_projects"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_narrative_projects_id_tenant"),
        UniqueConstraint("tenant_id", "creation_key", name="uq_narrative_projects_creation_key"),
        ForeignKeyConstraint(
            ["head_revision_id", "id", "tenant_id"],
            [
                "narrative_revisions.id",
                "narrative_revisions.project_id",
                "narrative_revisions.tenant_id",
            ],
            name="fk_narrative_project_head",
            use_alter=True,
            ondelete="RESTRICT",
        ),
        CheckConstraint("next_revision_number > 0", name="ck_narrative_project_sequence"),
        Index("ix_narrative_projects_tenant_created", "tenant_id", "created_at", "id"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(200))
    creation_key: Mapped[UUID]
    creation_hash: Mapped[str] = mapped_column(String(64))
    head_revision_id: Mapped[UUID | None]
    next_revision_number: Mapped[int] = mapped_column(Integer, default=1)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NarrativeRevision(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "narrative_revisions"
    __table_args__ = (
        UniqueConstraint("id", "project_id", "tenant_id", name="uq_narrative_revision_scope"),
        UniqueConstraint("project_id", "revision_number", name="uq_narrative_revision_number"),
        UniqueConstraint("project_id", "idempotency_key", name="uq_narrative_revision_key"),
        ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["narrative_projects.id", "narrative_projects.tenant_id"],
            name="fk_narrative_revision_project",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["parent_revision_id", "project_id", "tenant_id"],
            [
                "narrative_revisions.id",
                "narrative_revisions.project_id",
                "narrative_revisions.tenant_id",
            ],
            name="fk_narrative_revision_parent",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["observed_head_revision_id", "project_id", "tenant_id"],
            [
                "narrative_revisions.id",
                "narrative_revisions.project_id",
                "narrative_revisions.tenant_id",
            ],
            name="fk_narrative_revision_observed",
            ondelete="RESTRICT",
        ),
        CheckConstraint("revision_number > 0", name="ck_narrative_revision_sequence"),
    )
    tenant_id: Mapped[UUID]
    project_id: Mapped[UUID]
    revision_number: Mapped[int] = mapped_column(Integer)
    parent_revision_id: Mapped[UUID | None]
    observed_head_revision_id: Mapped[UUID | None]
    conflicted: Mapped[bool] = mapped_column(Boolean, default=False)
    idempotency_key: Mapped[UUID]
    request_hash: Mapped[str] = mapped_column(String(64))
    story_json: Mapped[str] = mapped_column(Text)
    notices: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    author_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
