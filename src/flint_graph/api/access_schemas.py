"""Request and response bodies for invite-only access and credits (ADR 0058, 0059)."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PriceResponse(BaseModel):
    credits: int
    kind: str
    label: str
    unit: str
    # Quantities are counted in blocks of this many units (100 training steps).
    per: int


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
    # The balance; None without a grant, or on a grant made before credits.
    credits: int | None
    # True when nothing is enforced: open mode, an operator, or an unlimited grant.
    unlimited: bool
    # On their own server: nothing is charged, and what they use is counted (ADR 0075).
    own_server: bool = False
    credits_used: int = 0
    prices: dict[str, PriceResponse]
    # The price item of an assistant turn on this server; None when it is off.
    assistant_item: str | None


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
    # None grants the server's default credits; unlimited ignores both.
    credits: int | None = Field(default=None, ge=0, le=10_000_000)
    unlimited: bool = False
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
    credits: int | None
    unlimited: bool
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
    # What a new invitation grants when the operator sets no limits or credits.
    default_limits: dict[str, dict[str, int]]
    default_credits: int


class GrantResponse(BaseModel):
    id: UUID
    user_id: UUID
    email: str | None
    display_name: str | None
    status: Literal["active", "suspended"]
    invitation_label: str | None
    limits: dict[str, Any]
    usage: dict[str, dict[str, int]]
    credits: int | None
    unlimited: bool
    created_at: datetime


class GrantList(BaseModel):
    grants: list[GrantResponse]


class CreditChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    change: Literal["add", "remove", "set"]
    amount: int = Field(ge=0, le=10_000_000)
    note: str | None = Field(default=None, max_length=300)


class UnlimitedChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unlimited: bool
    note: str | None = Field(default=None, max_length=300)


class CreditEntryResponse(BaseModel):
    id: UUID
    change: Literal["join", "charge", "add", "remove", "set", "unlimited", "limited"]
    amount: int
    balance: int | None
    item: str | None
    quantity: int | None
    subject: str | None
    note: str | None
    # The operator who made an adjustment.
    actor_email: str | None
    created_at: datetime


class CreditHistory(BaseModel):
    entries: list[CreditEntryResponse]
