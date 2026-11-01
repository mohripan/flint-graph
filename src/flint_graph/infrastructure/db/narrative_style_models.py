"""Private versioned training artifacts, independent of game assets."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from flint_graph.infrastructure.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class NarrativeStyleJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "narrative_style_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["narrative_projects.id", "narrative_projects.tenant_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("project_id", "idempotency_key", name="uq_style_job_key"),
        UniqueConstraint("id", "project_id", "tenant_id", name="uq_style_job_scope"),
        Index("ix_style_jobs_workspace", "tenant_id", "status", "created_at"),
        CheckConstraint(
            "status IN ('queued','running','completed','failed','cancelled')",
            name="ck_style_status",
        ),
        CheckConstraint(
            "steps BETWEEN 20 AND 400 AND progress BETWEEN 0 AND steps", name="ck_style_progress"
        ),
        CheckConstraint("seed BETWEEN 0 AND 4294967295", name="ck_style_seed"),
    )
    tenant_id: Mapped[UUID]
    project_id: Mapped[UUID]
    author_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(80))
    idempotency_key: Mapped[UUID]
    request_hash: Mapped[str] = mapped_column(String(64))
    model_manifest_sha256: Mapped[str] = mapped_column(String(64))
    dataset_sha256: Mapped[str] = mapped_column(String(64))
    recipe_sha256: Mapped[str] = mapped_column(String(64))
    images: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    trigger: Mapped[str] = mapped_column(String(48))
    steps: Mapped[int]
    seed: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    progress: Mapped[int] = mapped_column(default=0)
    workflow_run_id: Mapped[UUID | None]
    execution_token: Mapped[UUID | None]
    activity_attempt: Mapped[int] = mapped_column(default=0)
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    weights_key: Mapped[str | None] = mapped_column(String(500))
    weights_sha256: Mapped[str | None] = mapped_column(String(64))
    weights_size: Mapped[int | None]
    losses: Mapped[list[float] | None] = mapped_column(JSON)
    runtime: Mapped[dict[str, str] | None] = mapped_column(JSON)
    tracking_run_id: Mapped[str | None] = mapped_column(String(64))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NarrativePoseStyle(Base):
    __tablename__ = "narrative_pose_styles"
    __table_args__ = (
        CheckConstraint("strength BETWEEN 0.1 AND 1", name="ck_pose_style_strength"),
        ForeignKeyConstraint(["job_id"], ["narrative_pose_jobs.job_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["job_id", "project_id", "tenant_id"],
            [
                "narrative_image_jobs.id",
                "narrative_image_jobs.project_id",
                "narrative_image_jobs.tenant_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["style_id", "project_id", "tenant_id"],
            [
                "narrative_style_jobs.id",
                "narrative_style_jobs.project_id",
                "narrative_style_jobs.tenant_id",
            ],
            ondelete="RESTRICT",
        ),
    )
    job_id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID]
    project_id: Mapped[UUID]
    style_id: Mapped[UUID]
    strength: Mapped[float]
    weights_sha256: Mapped[str] = mapped_column(String(64))
