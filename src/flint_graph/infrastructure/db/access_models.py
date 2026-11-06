"""Invite-only access: invitations, grants and usage charges (ADR 0058)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from flint_graph.infrastructure.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AccessInvitation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A key anyone may redeem, or an invitation for one verified email address."""

    __tablename__ = "access_invitations"
    __table_args__ = (
        CheckConstraint("kind IN ('key', 'email')", name="ck_access_invitations_kind"),
        CheckConstraint(
            "(kind = 'key' AND key_sha256 IS NOT NULL AND email IS NULL)"
            " OR (kind = 'email' AND email IS NOT NULL AND key_sha256 IS NULL)",
            name="ck_access_invitations_target",
        ),
        CheckConstraint(
            "max_redemptions >= 1 AND redemption_count >= 0"
            " AND redemption_count <= max_redemptions",
            name="ck_access_invitations_redemptions",
        ),
        UniqueConstraint("key_sha256", name="uq_access_invitations_key"),
        Index("ix_access_invitations_email", "email"),
    )

    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    # Only a hash of the normalized key is kept; the key itself is shown once.
    key_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    key_hint: Mapped[str | None] = mapped_column(String(4), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    max_redemptions: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    redemption_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    limits: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class AccessGrant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One person's access, with the limits copied from the invitation they used."""

    __tablename__ = "access_grants"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'suspended')", name="ck_access_grants_status"),
        UniqueConstraint("user_id", name="uq_access_grants_user"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    invitation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("access_invitations.id", ondelete="SET NULL"), nullable=True
    )
    limits: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UsageCharge(UUIDPrimaryKeyMixin, Base):
    """Units admitted for one person, counted against their grant's limits."""

    __tablename__ = "usage_charges"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('image', 'voice', 'assistant', 'release', 'training')",
            name="ck_usage_charges_kind",
        ),
        CheckConstraint("units > 0", name="ck_usage_charges_units"),
        Index("ix_usage_charges_user_kind_time", "user_id", "kind", "created_at"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    units: Mapped[int] = mapped_column(Integer, nullable=False)
    subject: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
