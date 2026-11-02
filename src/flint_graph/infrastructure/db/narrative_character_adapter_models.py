"""Immutable reviewed-look targets for private training versions."""

from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from flint_graph.infrastructure.db.base import Base


class NarrativeCharacterAdapter(Base):
    __tablename__ = "narrative_character_adapters"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "project_id", "tenant_id"],
            [
                "narrative_style_jobs.id",
                "narrative_style_jobs.project_id",
                "narrative_style_jobs.tenant_id",
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
        Index("ix_character_adapter_look", "tenant_id", "project_id", "character_id", "look_id"),
    )
    job_id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID]
    tenant_id: Mapped[UUID]
    character_id: Mapped[str] = mapped_column(String(64))
    look_id: Mapped[UUID]
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)


class NarrativePoseCharacterAdapter(Base):
    """The additional, explicitly typed character role; legacy style bindings stay valid."""

    __tablename__ = "narrative_pose_character_adapters"
    __table_args__ = (
        CheckConstraint("strength BETWEEN 0.1 AND 1", name="ck_pose_character_strength"),
        ForeignKeyConstraint(["job_id"], ["narrative_pose_jobs.job_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["adapter_id"], ["narrative_character_adapters.job_id"], ondelete="RESTRICT"
        ),
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
            ["adapter_id", "project_id", "tenant_id"],
            [
                "narrative_style_jobs.id",
                "narrative_style_jobs.project_id",
                "narrative_style_jobs.tenant_id",
            ],
            ondelete="RESTRICT",
        ),
    )
    job_id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID]
    tenant_id: Mapped[UUID]
    adapter_id: Mapped[UUID]
    strength: Mapped[float]
    weights_sha256: Mapped[str] = mapped_column(String(64))
