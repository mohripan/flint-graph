"""Voice references and the records around cloned and expressive voices (ADR 0044)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from flint_graph.infrastructure.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class NarrativeVoiceReference(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A private voice sample a character voice may be cloned from (#175).

    Never a story asset: it lives in its own table and object prefix, so a story,
    package, playtest, release or NOTICES can never name it. Deleting it removes the
    audio and blocks new jobs; the row keeps the consent record that earlier clips'
    provenance points to.
    """

    __tablename__ = "narrative_voice_references"
    __table_args__ = (
        UniqueConstraint(
            "id", "project_id", "tenant_id", name="uq_narrative_voice_reference_scope"
        ),
        ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["narrative_projects.id", "narrative_projects.tenant_id"],
            name="fk_narrative_voice_reference_project",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "consent IN ('self','permission')", name="ck_narrative_voice_reference_consent"
        ),
        CheckConstraint(
            "source IN ('upload','recording')", name="ck_narrative_voice_reference_source"
        ),
        CheckConstraint(
            "(status = 'active' AND deleted_at IS NULL AND deleted_by_user_id IS NULL) OR "
            "(status = 'deleted' AND deleted_at IS NOT NULL AND deleted_by_user_id IS NOT NULL)",
            name="ck_narrative_voice_reference_status",
        ),
        CheckConstraint(
            "duration_ms BETWEEN 5000 AND 30000 AND size_bytes > 0 AND channels IN (1, 2)",
            name="ck_narrative_voice_reference_audio",
        ),
        Index("ix_narrative_voice_reference_project", "project_id", "status", "created_at"),
    )
    tenant_id: Mapped[UUID]
    project_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(String(120))
    speaker_name: Mapped[str] = mapped_column(String(120))
    # "self": the declarer's own voice; "permission": the named speaker agreed.
    consent: Mapped[str] = mapped_column(String(16))
    consent_declared_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    consent_declared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # What the speaker says, which some models use to clone more faithfully.
    transcript: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer)
    sample_rate: Mapped[int] = mapped_column(Integer)
    channels: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="active")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
