"""Request and response bodies for invite-only access (ADR 0058)."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AccessStatus(BaseModel):
    mode: Literal["open", "invite"]
    has_access: bool
    is_admin: bool
    status: Literal["none", "active", "suspended"]
    email: str | None
    display_name: str | None
    limits: dict[str, Any] | None
    usage: dict[str, dict[str, int]]
    email_invitation: bool


class JoinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str | None = Field(default=None, max_length=64)


class InvitationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["key", "email"]
    label: str = Field(min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=320)
    max_redemptions: int = Field(default=1, ge=1, le=1000)
    # None grants the server's default limits.
    limits: dict[str, dict[str, int]] | None = None
    expires_at: datetime | None = None


class InvitationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kind: Literal["key", "email"]
    label: str
    key_hint: str | None
    email: str | None
    max_redemptions: int
    redemption_count: int
    limits: dict[str, Any]
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class InvitationCreated(BaseModel):
    invitation: InvitationResponse
    # Shown once: only its hash is stored.
    key: str | None
    link: str


class InvitationList(BaseModel):
    invitations: list[InvitationResponse]
    # What a new invitation grants when the operator sets no limits.
    default_limits: dict[str, dict[str, int]]


class GrantResponse(BaseModel):
    id: UUID
    user_id: UUID
    email: str | None
    display_name: str | None
    status: Literal["active", "suspended"]
    invitation_label: str | None
    limits: dict[str, Any]
    usage: dict[str, dict[str, int]]
    created_at: datetime


class GrantList(BaseModel):
    grants: list[GrantResponse]
