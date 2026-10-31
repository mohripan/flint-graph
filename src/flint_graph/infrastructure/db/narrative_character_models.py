"""Character profiles, local image-generation jobs and immutable images (ADR 0039)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from flint_graph.infrastructure.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# Transparent sprites are full-body character renders; a completed one names the
# segmenter that cut it out (migration 0025).
TRANSPARENT_RULE = "NOT transparent OR (purpose = 'character_portrait' AND framing = 'full_body')"
CUTOUT_RULE = (
    "((cutout_model IS NULL AND cutout_sha256 IS NULL) "
    "OR (transparent AND cutout_model IS NOT NULL AND cutout_sha256 IS NOT NULL)) "
    "AND (status <> 'completed' OR NOT transparent OR cutout_model IS NOT NULL)"
)
# Expression jobs repaint the face of a base asset of the same project (migration 0026).
PURPOSE_RULE = (
    "(purpose IN ('character_portrait','character_expression') AND character_id IS NOT NULL) "
    "OR (purpose = 'background' AND character_id IS NULL)"
)
EXPRESSION_RULE = (
    "(purpose = 'character_expression') = (base_asset_id IS NOT NULL AND face_box IS NOT NULL "
    "AND strength IS NOT NULL AND expressions IS NOT NULL AND prompts IS NOT NULL)"
)
# High-resolution character renders are upscaled by one of two scales and repainted
# lightly (migration 0027); expression and background jobs never are.
HIRES_RULE = (
    "(hires_scale IS NULL AND hires_strength IS NULL) "
    "OR (purpose = 'character_portrait' AND hires_scale IN (1.5, 2.0) "
    "AND hires_strength BETWEEN 0.2 AND 0.6)"
)


class NarrativeImageJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One fenced local generation of up to four candidate images."""

    __tablename__ = "narrative_image_jobs"
    __table_args__ = (
        UniqueConstraint("id", "project_id", "tenant_id", name="uq_narrative_image_job_scope"),
        UniqueConstraint("project_id", "idempotency_key", name="uq_narrative_image_job_key"),
        ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["narrative_projects.id", "narrative_projects.tenant_id"],
            name="fk_narrative_image_job_project",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('queued','running','completed','failed','cancelled')",
            name="ck_narrative_image_job_status",
        ),
        CheckConstraint(
            "(status = 'running' AND execution_token IS NOT NULL) OR "
            "(status <> 'running' AND execution_token IS NULL)",
            name="ck_narrative_image_job_execution_fence",
        ),
        CheckConstraint(
            "status <> 'completed' OR NOT cancel_requested",
            name="ck_narrative_image_job_not_cancelled_completed",
        ),
        CheckConstraint(
            "(workflow_run_id IS NULL AND activity_attempt IS NULL) OR "
            "(workflow_run_id IS NOT NULL AND activity_attempt IS NOT NULL "
            "AND activity_attempt >= 0)",
            name="ck_narrative_image_job_workflow_owner",
        ),
        CheckConstraint("count BETWEEN 1 AND 4", name="ck_narrative_image_job_count"),
        CheckConstraint("progress BETWEEN 0 AND count", name="ck_narrative_image_job_progress"),
        CheckConstraint(PURPOSE_RULE, name="ck_narrative_image_job_purpose"),
        CheckConstraint(EXPRESSION_RULE, name="ck_narrative_image_job_expression"),
        ForeignKeyConstraint(
            ["base_asset_id", "project_id", "tenant_id"],
            ["narrative_assets.id", "narrative_assets.project_id", "narrative_assets.tenant_id"],
            name="fk_narrative_image_job_base_asset",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        CheckConstraint(TRANSPARENT_RULE, name="ck_narrative_image_job_transparent"),
        CheckConstraint(CUTOUT_RULE, name="ck_narrative_image_job_cutout"),
        CheckConstraint(HIRES_RULE, name="ck_narrative_image_job_hires"),
        Index("ix_narrative_image_job_purpose", "project_id", "purpose", "created_at", "id"),
        Index(
            "ix_narrative_image_job_active",
            "tenant_id",
            postgresql_where=text("status IN ('queued','running')"),
            sqlite_where=text("status IN ('queued','running')"),
        ),
        Index("ix_narrative_image_job_run_status", "status", "workflow_run_id"),
        Index("ix_narrative_image_job_character", "project_id", "character_id", "created_at", "id"),
    )
    tenant_id: Mapped[UUID]
    project_id: Mapped[UUID]
    character_id: Mapped[str | None] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(32), default="character_portrait")
    requested_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    idempotency_key: Mapped[UUID]
    request_hash: Mapped[str] = mapped_column(String(64))
    appearance: Mapped[str] = mapped_column(Text)
    character_type: Mapped[str] = mapped_column(String(16))
    framing: Mapped[str] = mapped_column(String(16))
    prompt: Mapped[str] = mapped_column(Text)
    negative_prompt: Mapped[str] = mapped_column(Text)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    steps: Mapped[int] = mapped_column(Integer)
    guidance: Mapped[float] = mapped_column(Float)
    seeds: Mapped[list[int]] = mapped_column(JSON)
    count: Mapped[int] = mapped_column(Integer)
    transparent: Mapped[bool] = mapped_column(Boolean, default=False)
    # Expressions (ADR 0041): the face of this base asset, repainted once per expression.
    base_asset_id: Mapped[UUID | None]
    face_box: Mapped[list[int] | None] = mapped_column(JSON)
    strength: Mapped[float | None] = mapped_column(Float)
    expressions: Mapped[list[str] | None] = mapped_column(JSON)
    prompts: Mapped[list[str] | None] = mapped_column(JSON)
    hires_scale: Mapped[float | None] = mapped_column(Float)
    hires_strength: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    execution_token: Mapped[UUID | None]
    workflow_run_id: Mapped[UUID | None]
    activity_attempt: Mapped[int | None]
    error_code: Mapped[str | None] = mapped_column(String(80))
    model: Mapped[str | None] = mapped_column(String(200))
    cutout_model: Mapped[str | None] = mapped_column(String(200))
    cutout_sha256: Mapped[str | None] = mapped_column(String(64))
    runtime: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    prompt_tokens: Mapped[int | None]
    truncated: Mapped[bool | None] = mapped_column(Boolean)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NarrativeAsset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One immutable, hash-verified PNG (with thumbnail) owned by a project."""

    __tablename__ = "narrative_assets"
    __table_args__ = (
        UniqueConstraint("id", "project_id", "tenant_id", name="uq_narrative_asset_scope"),
        UniqueConstraint("job_id", "job_index", name="uq_narrative_asset_job_index"),
        ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["narrative_projects.id", "narrative_projects.tenant_id"],
            name="fk_narrative_asset_project",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["job_id", "project_id", "tenant_id"],
            [
                "narrative_image_jobs.id",
                "narrative_image_jobs.project_id",
                "narrative_image_jobs.tenant_id",
            ],
            name="fk_narrative_asset_job",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('candidate','approved','discarded')", name="ck_narrative_asset_status"
        ),
        CheckConstraint(
            "kind IN ('character_portrait','background','sprite','image','font')",
            name="ck_narrative_asset_kind",
        ),
        CheckConstraint(
            "media_type IN ('image/png','font/ttf','font/otf')",
            name="ck_narrative_asset_media_type",
        ),
        CheckConstraint(
            "size_bytes > 0 AND ((media_type = 'image/png' AND width > 0 AND height > 0) "
            "OR (media_type <> 'image/png' AND width IS NULL AND height IS NULL))",
            name="ck_narrative_asset_shape",
        ),
        CheckConstraint(
            "status <> 'approved' OR approved_at IS NOT NULL",
            name="ck_narrative_asset_approval",
        ),
        CheckConstraint("source IN ('generated','uploaded')", name="ck_narrative_asset_source"),
        CheckConstraint(
            "source <> 'uploaded' OR (rights_declared_at IS NOT NULL "
            "AND rights_declared_by_user_id IS NOT NULL)",
            name="ck_narrative_asset_rights",
        ),
        ForeignKeyConstraint(
            ["rights_declared_by_user_id"],
            ["users.id"],
            name="fk_narrative_asset_rights_user",
            ondelete="RESTRICT",
        ),
        Index("ix_narrative_assets_project", "project_id", "created_at", "id"),
        Index("ix_narrative_assets_project_kind", "project_id", "kind", "created_at"),
        # One live row per file per project, so story bindings by SHA-256 are unambiguous.
        Index(
            "uq_narrative_asset_project_sha",
            "tenant_id",
            "project_id",
            "sha256",
            unique=True,
            postgresql_where=text("status <> 'discarded'"),
            sqlite_where=text("status <> 'discarded'"),
        ),
    )
    tenant_id: Mapped[UUID]
    project_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(120))
    job_id: Mapped[UUID | None]
    job_index: Mapped[int | None]
    character_id: Mapped[str | None] = mapped_column(String(64))
    media_type: Mapped[str] = mapped_column(String(32), default="image/png")
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    # Generated images carry a smaller thumbnail; uploads serve the original instead.
    thumbnail_sha256: Mapped[str | None] = mapped_column(String(64))
    thumbnail_size_bytes: Mapped[int | None] = mapped_column(Integer)
    thumbnail_width: Mapped[int | None] = mapped_column(Integer)
    thumbnail_height: Mapped[int | None] = mapped_column(Integer)
    seed: Mapped[int | None] = mapped_column(BigInteger)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON)
    license: Mapped[str] = mapped_column(String(120))
    notice: Mapped[str | None] = mapped_column(Text)
    rights_declared_by_user_id: Mapped[UUID | None]
    rights_declared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="candidate")
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    approved_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NarrativeCharacterProfile(TimestampMixin, Base):
    """Editor-only appearance and chosen portrait for one story character ID."""

    __tablename__ = "narrative_character_profiles"
    __table_args__ = (
        PrimaryKeyConstraint("project_id", "character_id"),
        ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["narrative_projects.id", "narrative_projects.tenant_id"],
            name="fk_narrative_character_profile_project",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["portrait_asset_id", "project_id", "tenant_id"],
            [
                "narrative_assets.id",
                "narrative_assets.project_id",
                "narrative_assets.tenant_id",
            ],
            name="fk_narrative_character_profile_portrait",
            ondelete="RESTRICT",
        ),
        CheckConstraint("version > 0", name="ck_narrative_character_profile_version"),
    )
    project_id: Mapped[UUID]
    character_id: Mapped[str] = mapped_column(String(64))
    tenant_id: Mapped[UUID]
    appearance: Mapped[str] = mapped_column(Text, default="")
    character_type: Mapped[str] = mapped_column(String(16))
    framing: Mapped[str] = mapped_column(String(16))
    portrait_asset_id: Mapped[UUID | None]
    version: Mapped[int] = mapped_column(Integer)
    updated_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
