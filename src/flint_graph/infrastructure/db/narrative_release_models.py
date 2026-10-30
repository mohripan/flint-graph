"""Private immutable release identities and fenced mutable execution attempts."""

from datetime import datetime
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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from flint_graph.infrastructure.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class NarrativeRelease(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "narrative_releases"
    __table_args__ = (
        UniqueConstraint("id", "project_id", "tenant_id", name="uq_narrative_release_scope"),
        UniqueConstraint("project_id", "creation_key", name="uq_narrative_release_key"),
        ForeignKeyConstraint(
            ["revision_id", "project_id", "tenant_id"],
            [
                "narrative_revisions.id",
                "narrative_revisions.project_id",
                "narrative_revisions.tenant_id",
            ],
            name="fk_narrative_release_revision",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_narrative_release_project_created", "tenant_id", "project_id", "created_at", "id"
        ),
    )
    tenant_id: Mapped[UUID]
    project_id: Mapped[UUID]
    revision_id: Mapped[UUID]
    creation_key: Mapped[UUID]
    request_hash: Mapped[str] = mapped_column(String(64))
    package_hash: Mapped[str] = mapped_column(String(64))
    compiler_version: Mapped[str] = mapped_column(String(32))
    runtime_version: Mapped[str] = mapped_column(String(32))
    godot_version: Mapped[str] = mapped_column(String(32))
    toolchain_sha256: Mapped[str] = mapped_column(String(64))
    builder_image_digest: Mapped[str] = mapped_column(String(71))
    creator_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NarrativeReleaseJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "narrative_release_jobs"
    __table_args__ = (
        UniqueConstraint(
            "id", "release_id", "project_id", "tenant_id", name="uq_narrative_release_job_scope"
        ),
        UniqueConstraint("release_id", "attempt_number", name="uq_narrative_release_attempt"),
        UniqueConstraint("release_id", "retry_key", name="uq_narrative_release_retry_key"),
        ForeignKeyConstraint(
            ["release_id", "project_id", "tenant_id"],
            [
                "narrative_releases.id",
                "narrative_releases.project_id",
                "narrative_releases.tenant_id",
            ],
            name="fk_narrative_release_job_release",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "attempt_number > 0 AND next_event_sequence > 0", name="ck_narrative_release_sequences"
        ),
        CheckConstraint(
            "status IN ('queued','running','completed','failed','cancelled')",
            name="ck_narrative_release_status",
        ),
        CheckConstraint(
            "(status = 'running' AND execution_token IS NOT NULL) OR "
            "(status <> 'running' AND execution_token IS NULL)",
            name="ck_narrative_release_execution_fence",
        ),
        CheckConstraint(
            "status <> 'completed' OR NOT cancel_requested",
            name="ck_narrative_release_not_cancelled_completed",
        ),
        Index(
            "uq_narrative_release_active_job",
            "release_id",
            unique=True,
            postgresql_where=text("status IN ('queued','running')"),
            sqlite_where=text("status IN ('queued','running')"),
        ),
        Index("ix_narrative_release_workspace_status", "tenant_id", "status"),
    )
    tenant_id: Mapped[UUID]
    project_id: Mapped[UUID]
    release_id: Mapped[UUID]
    attempt_number: Mapped[int] = mapped_column(Integer)
    retry_key: Mapped[UUID | None]
    status: Mapped[str] = mapped_column(String(16), default="queued")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    execution_token: Mapped[UUID | None]
    next_event_sequence: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))


class NarrativeReleaseEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "narrative_release_events"
    __table_args__ = (
        UniqueConstraint("job_id", "sequence", name="uq_narrative_release_event_sequence"),
        ForeignKeyConstraint(
            ["job_id", "release_id", "project_id", "tenant_id"],
            [
                "narrative_release_jobs.id",
                "narrative_release_jobs.release_id",
                "narrative_release_jobs.project_id",
                "narrative_release_jobs.tenant_id",
            ],
            name="fk_narrative_release_event_job",
            ondelete="RESTRICT",
        ),
        CheckConstraint("sequence > 0", name="ck_narrative_release_event_sequence"),
    )
    tenant_id: Mapped[UUID]
    project_id: Mapped[UUID]
    release_id: Mapped[UUID]
    job_id: Mapped[UUID]
    sequence: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NarrativeReleaseArtifact(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "narrative_release_artifacts"
    __table_args__ = (
        UniqueConstraint("release_id", "kind", name="uq_narrative_release_artifact_kind"),
        ForeignKeyConstraint(
            ["job_id", "release_id", "project_id", "tenant_id"],
            [
                "narrative_release_jobs.id",
                "narrative_release_jobs.release_id",
                "narrative_release_jobs.project_id",
                "narrative_release_jobs.tenant_id",
            ],
            name="fk_narrative_release_artifact_job",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "kind IN ('source','web','manifest')", name="ck_narrative_release_artifact_kind"
        ),
        CheckConstraint(
            "size_bytes > 0 AND size_bytes <= 67108864", name="ck_narrative_release_artifact_size"
        ),
        CheckConstraint(
            "kind <> 'manifest' OR size_bytes <= 1048576", name="ck_narrative_release_manifest_size"
        ),
    )
    tenant_id: Mapped[UUID]
    project_id: Mapped[UUID]
    release_id: Mapped[UUID]
    job_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(String(16))
    object_key: Mapped[str] = mapped_column(String(1024))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    media_type: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
