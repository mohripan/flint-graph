"""Private editor-only reviewed looks; no fields enter a story package."""

from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from flint_graph.infrastructure.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class NarrativeCharacterLook(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "narrative_character_looks"
    __table_args__ = (
        Index("ix_character_look_project", "tenant_id", "project_id", "character_id", "created_at"),
        UniqueConstraint(
            "id", "project_id", "tenant_id", "character_id", name="uq_character_look_scope"
        ),
        UniqueConstraint("project_id", "creation_key", name="uq_character_look_key"),
        ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["narrative_projects.id", "narrative_projects.tenant_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["asset_id", "project_id", "tenant_id"],
            ["narrative_assets.id", "narrative_assets.project_id", "narrative_assets.tenant_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["parent_look_id", "project_id", "tenant_id", "character_id"],
            [
                "narrative_character_looks.id",
                "narrative_character_looks.project_id",
                "narrative_character_looks.tenant_id",
                "narrative_character_looks.character_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("length(name) BETWEEN 1 AND 80", name="ck_character_look_name"),
    )
    tenant_id: Mapped[UUID]
    project_id: Mapped[UUID]
    character_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(80))
    asset_id: Mapped[UUID]
    source_sha256: Mapped[str] = mapped_column(String(64))
    identity_tags: Mapped[list[str]] = mapped_column(JSON)
    clothing_tags: Mapped[list[str]] = mapped_column(JSON)
    character_type: Mapped[str] = mapped_column(String(16))
    parent_look_id: Mapped[UUID | None]
    sha256: Mapped[str] = mapped_column(String(64))
    creation_key: Mapped[UUID]
    request_hash: Mapped[str] = mapped_column(String(64))
    reviewed_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    tagger_observation: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    prompt_bundle_sha256: Mapped[str] = mapped_column(
        ForeignKey("prompt_bundles.sha256", ondelete="RESTRICT")
    )
    policy_sha256: Mapped[str] = mapped_column(String(64))


class NarrativeLookSelection(TimestampMixin, Base):
    __tablename__ = "narrative_look_selections"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["narrative_projects.id", "narrative_projects.tenant_id"],
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
        CheckConstraint("version > 0", name="ck_look_selection_version"),
    )
    project_id: Mapped[UUID] = mapped_column(primary_key=True)
    character_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[UUID]
    look_id: Mapped[UUID | None]
    version: Mapped[int]


class NarrativeLookJob(Base):
    __tablename__ = "narrative_look_jobs"
    __table_args__ = (
        Index("ix_look_jobs_character", "tenant_id", "project_id", "character_id"),
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
    )
    job_id: Mapped[UUID] = mapped_column(primary_key=True)
    character_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[UUID]
    project_id: Mapped[UUID]
    look_id: Mapped[UUID]
    request_hash: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)


class NarrativeCandidateReview(TimestampMixin, Base):
    __tablename__ = "narrative_candidate_reviews"
    __table_args__ = (
        Index("ix_candidate_reviews_assets", "tenant_id", "project_id", "asset_id"),
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
        ForeignKeyConstraint(
            ["asset_id", "project_id", "tenant_id"],
            ["narrative_assets.id", "narrative_assets.project_id", "narrative_assets.tenant_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "identity IN ('same','drifted','unknown') AND clothes IN ('same','drifted','unknown')",
            name="ck_candidate_review_labels",
        ),
        CheckConstraint("version > 0", name="ck_candidate_review_version"),
    )
    look_id: Mapped[UUID] = mapped_column(primary_key=True)
    asset_id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID]
    project_id: Mapped[UUID]
    character_id: Mapped[str] = mapped_column(String(64))
    source_sha256: Mapped[str] = mapped_column(String(64))
    candidate_sha256: Mapped[str] = mapped_column(String(64))
    identity: Mapped[str] = mapped_column(String(16))
    clothes: Mapped[str] = mapped_column(String(16))
    notes: Mapped[str] = mapped_column(String(1200))
    version: Mapped[int]
    reviewed_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class NarrativeLookObservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "narrative_look_observations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["asset_id", "project_id", "tenant_id"],
            ["narrative_assets.id", "narrative_assets.project_id", "narrative_assets.tenant_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "asset_id", "source_sha256", "tagger_sha256", name="uq_look_observation_source"
        ),
    )
    asset_id: Mapped[UUID]
    tenant_id: Mapped[UUID]
    project_id: Mapped[UUID]
    source_sha256: Mapped[str] = mapped_column(String(64))
    tagger_sha256: Mapped[str] = mapped_column(String(64))
    observation: Mapped[dict[str, Any]] = mapped_column(JSON)
