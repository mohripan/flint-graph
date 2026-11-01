"""Immutable model/reference plans extending the existing image-job ledger."""

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from flint_graph.infrastructure.db.base import Base


class NarrativePoseJob(Base):
    __tablename__ = "narrative_pose_jobs"
    __table_args__ = (
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
            ["look_id", "project_id", "tenant_id", "character_id"],
            [
                "narrative_character_looks.id",
                "narrative_character_looks.project_id",
                "narrative_character_looks.tenant_id",
                "narrative_character_looks.character_id",
            ],
            ondelete="RESTRICT",
        ),
        Index("ix_pose_jobs_character", "tenant_id", "project_id", "character_id"),
    )
    job_id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID]
    project_id: Mapped[UUID]
    character_id: Mapped[str] = mapped_column(String(64))
    look_id: Mapped[UUID]
    pose: Mapped[str] = mapped_column(Text)
    model_manifest_sha256: Mapped[str] = mapped_column(String(64))
    cutout_manifest_sha256: Mapped[str | None] = mapped_column(String(64))


class NarrativePoseReference(Base):
    __tablename__ = "narrative_pose_references"
    __table_args__ = (
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
            ["asset_id", "project_id", "tenant_id"],
            ["narrative_assets.id", "narrative_assets.project_id", "narrative_assets.tenant_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("job_id", "asset_id", name="uq_pose_reference_asset"),
        CheckConstraint("position IN (0,1)", name="ck_pose_reference_position"),
        CheckConstraint(
            "(position=0 AND view='primary') OR "
            "(position=1 AND view IN ('front','side','back','detail'))",
            name="ck_pose_reference_view",
        ),
    )
    job_id: Mapped[UUID] = mapped_column(primary_key=True)
    position: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID]
    project_id: Mapped[UUID]
    asset_id: Mapped[UUID]
    view: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(200))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int]
