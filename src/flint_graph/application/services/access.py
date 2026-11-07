"""Invite-only access: who may use the Studio, and how much they may generate.

In ``invite`` mode a signed-in person needs an active grant, made by redeeming an
invitation key or an email invitation, unless they are a configured operator (ADR 0058).
Each admitted generation counts units against the grant's caps and spends credits from
its balance at the item's price (ADR 0059), in the same transaction as the job, after
the job's own idempotency check. Every balance change is written to the credit ledger.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.credit_prices import PriceItem, resolve_prices
from flint_graph.application.services.authz import AuthenticatedPrincipal
from flint_graph.config import DEFAULT_ACCESS_LIMITS, Settings
from flint_graph.domain.errors import DomainError, NotFoundError
from flint_graph.infrastructure.db.models import (
    AccessGrant,
    AccessInvitation,
    CreditLedgerEntry,
    UsageCharge,
    User,
)

KINDS = ("image", "voice", "assistant", "release", "training", "music")
DEFAULT_LIMITS = DEFAULT_ACCESS_LIMITS
_NOUNS = {
    "image": "images",
    "voice": "voice lines",
    "assistant": "assistant replies",
    "release": "release builds",
    "training": "training runs",
    "music": "music tracks",
}
# No 0/O, 1/I/L: keys are read aloud and retyped.
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_WINDOW = timedelta(hours=24)
_MAX_UNITS = 10_000_000
MAX_CREDITS = 10_000_000
# Where a request's access dependency leaves what charges need (see require_access).
_REQUEST_ACCESS = "flint_graph.access"
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]+$")


def new_key() -> str:
    chars = "".join(secrets.choice(_ALPHABET) for _ in range(16))
    return "FG-" + "-".join(chars[index : index + 4] for index in range(0, 16, 4))


def key_hash(key: str) -> str:
    normalized = re.sub(r"[\s-]+", "", key).upper()
    return sha256(normalized.encode("utf-8")).hexdigest()


def clean_limits(value: object) -> dict[str, dict[str, int]]:
    if not isinstance(value, dict):
        raise ValueError("Limits must map a kind to its limits.")
    cleaned: dict[str, dict[str, int]] = {}
    for kind, entry in value.items():
        if kind not in KINDS:
            raise ValueError(f"Unknown usage kind: {kind}.")
        if not isinstance(entry, dict):
            raise ValueError(f"Limits for {kind} must be an object.")
        item: dict[str, int] = {}
        for window, amount in entry.items():
            if window not in ("daily", "total"):
                raise ValueError(f"Use daily or total limits for {kind}.")
            if isinstance(amount, bool) or not isinstance(amount, int):
                raise ValueError(f"Limits for {kind} must be whole numbers.")
            if not 0 <= amount <= _MAX_UNITS:
                raise ValueError(f"Limits for {kind} must be between 0 and {_MAX_UNITS}.")
            item[window] = amount
        cleaned[kind] = item
    return cleaned


def limit_problem(
    limits: dict[str, Any], kind: str, units: int, used_day: int, used_total: int
) -> str | None:
    """Why charging ``units`` more of ``kind`` is refused, or None when it fits."""
    entry = limits.get(kind) or {}
    noun = _NOUNS[kind]
    daily, total = entry.get("daily"), entry.get("total")
    if daily == 0 or total == 0:
        return f"{noun.capitalize()} are not included in your invitation."
    if daily is not None and used_day + units > daily:
        left = max(0, daily - used_day)
        if not left:
            return f"You've used all {daily} {noun} you can make in 24 hours. Try again later."
        return f"That needs {units} {noun}, but only {left} of your {daily} per 24 hours are left."
    if total is not None and used_total + units > total:
        left = max(0, total - used_total)
        if not left:
            return f"You've used all {total} {noun} your invitation includes."
        return (
            f"That needs {units} {noun}, but only {left} of the {total}"
            " your invitation includes are left."
        )
    return None


def _credits(amount: int) -> str:
    return "1 credit" if amount == 1 else f"{amount} credits"


def credit_problem(price: PriceItem, *, quantity: int, balance: int) -> str:
    """Why a charge of ``quantity`` x ``price`` does not fit ``balance``, naming all three."""
    total = price.credits * quantity
    if quantity == 1:
        head = f"{price.label} costs {_credits(total)}"
    elif price.per == 1:
        head = f"{quantity} × {price.label} costs {_credits(total)} ({price.credits} each)"
    else:
        head = f"{price.label} costs {_credits(total)} ({price.credits} per {price.unit})"
    left = f"you have {balance} left" if balance else "you have none left"
    return f"{head}, but {left}. Ask the person who invited you for more credits."


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    # SQLite hands timezone-aware columns back naive; every stored time is UTC.
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def verified_email(principal: AuthenticatedPrincipal, settings: Settings) -> str | None:
    """The principal's email, only when the identity provider verified it."""
    email = (principal.email or "").strip().lower()
    if not email:
        return None
    if settings.auth_mode == "dev":
        return email
    verified = principal.claims.get("email_verified")
    return email if verified is True or verified == "true" else None


def is_operator(principal: AuthenticatedPrincipal, settings: Settings) -> bool:
    email = verified_email(principal, settings)
    admins = {item.strip().lower() for item in settings.access_admin_emails if item.strip()}
    if email is not None and email in admins:
        return True
    group = settings.oidc_system_admin_group
    groups = principal.claims.get(settings.oidc_groups_claim)
    return bool(group) and isinstance(groups, list) and group in groups


def access_required() -> DomainError:
    return DomainError(
        403,
        "Invitation required",
        "This Studio is invite-only. Join with an invitation key or an email invitation.",
        "access-required",
    )


def _invalid_invitation() -> DomainError:
    # One answer for unknown, expired, revoked and used-up invitations.
    return DomainError(
        404,
        "Invitation not valid",
        "That invitation is not valid. It may have expired or already been used.",
        "invitation-invalid",
    )


@dataclass(frozen=True, slots=True)
class RequestAccess:
    """What charges in this request need: who is exempt, and this deployment's prices."""

    user_id: UUID
    exempt: bool
    prices: dict[str, int]


async def require_access(
    session: AsyncSession, user: User, principal: AuthenticatedPrincipal, settings: Settings
) -> None:
    exempt = settings.access_mode == "open" or is_operator(principal, settings)
    # Charges run deep inside job services; the request's session carries the prices
    # there, so no service needs the settings.
    session.info[_REQUEST_ACCESS] = RequestAccess(
        user.id, exempt, dict(settings.access_credit_prices)
    )
    if exempt:
        return
    status = await session.scalar(select(AccessGrant.status).where(AccessGrant.user_id == user.id))
    if status != "active":
        raise access_required()


@dataclass(frozen=True, slots=True)
class AccessState:
    mode: str
    has_access: bool
    is_admin: bool
    status: str
    limits: dict[str, Any] | None
    usage: dict[str, dict[str, int]]
    email_invitation: bool
    credits: int | None
    # No credits are spent: open mode, an operator, or an unlimited grant.
    unlimited: bool
    prices: dict[str, PriceItem]


async def usage_summary(session: AsyncSession, user_id: UUID) -> dict[str, dict[str, int]]:
    since = _now() - _WINDOW
    rows = await session.execute(
        select(
            UsageCharge.kind,
            func.coalesce(
                func.sum(case((UsageCharge.created_at >= since, UsageCharge.units), else_=0)), 0
            ),
            func.coalesce(func.sum(UsageCharge.units), 0),
        )
        .where(UsageCharge.user_id == user_id)
        .group_by(UsageCharge.kind)
    )
    summary = {kind: {"day": 0, "total": 0} for kind in KINDS}
    for kind, day, total in rows:
        summary[kind] = {"day": int(day), "total": int(total)}
    return summary


async def _open_email_invitation(
    session: AsyncSession, email: str | None, *, lock: bool = False
) -> AccessInvitation | None:
    if email is None:
        return None
    query = (
        select(AccessInvitation)
        .where(AccessInvitation.kind == "email", AccessInvitation.email == email)
        .order_by(AccessInvitation.created_at)
    )
    for invitation in (await session.scalars(query.with_for_update() if lock else query)).all():
        if _redeemable(invitation):
            return invitation
    return None


def _redeemable(invitation: AccessInvitation) -> bool:
    expires_at = _aware(invitation.expires_at)
    return (
        invitation.revoked_at is None
        and (expires_at is None or expires_at > _now())
        and invitation.redemption_count < invitation.max_redemptions
    )


async def access_state(
    session: AsyncSession, user: User, principal: AuthenticatedPrincipal, settings: Settings
) -> AccessState:
    admin = is_operator(principal, settings)
    grant = await session.scalar(select(AccessGrant).where(AccessGrant.user_id == user.id))
    status = grant.status if grant is not None else "none"
    has_access = settings.access_mode == "open" or admin or status == "active"
    invited = (
        not has_access
        and status == "none"
        and await _open_email_invitation(session, verified_email(principal, settings)) is not None
    )
    return AccessState(
        mode=settings.access_mode,
        has_access=has_access,
        is_admin=admin,
        status=status,
        limits=dict(grant.limits) if grant is not None else None,
        usage=await usage_summary(session, user.id),
        email_invitation=invited,
        credits=grant.credits if grant is not None else None,
        unlimited=settings.access_mode == "open"
        or admin
        or (grant is not None and grant.unlimited),
        prices=resolve_prices(settings.access_credit_prices),
    )


async def join(
    session: AsyncSession,
    *,
    user: User,
    principal: AuthenticatedPrincipal,
    settings: Settings,
    key: str | None,
) -> None:
    """Redeem a key, or the email invitation addressed to this user."""
    if settings.access_mode == "open" or is_operator(principal, settings):
        return
    grant = await session.scalar(
        select(AccessGrant).where(AccessGrant.user_id == user.id).with_for_update()
    )
    if grant is not None:
        if grant.status != "active":
            raise DomainError(
                403,
                "Access suspended",
                "Your access to this Studio is suspended. Contact the person who invited you.",
                "access-suspended",
            )
        return
    if key:
        invitation = await session.scalar(
            select(AccessInvitation)
            .where(AccessInvitation.kind == "key", AccessInvitation.key_sha256 == key_hash(key))
            .with_for_update()
        )
        if invitation is not None and not _redeemable(invitation):
            invitation = None
    else:
        invitation = await _open_email_invitation(
            session, verified_email(principal, settings), lock=True
        )
    if invitation is None:
        raise _invalid_invitation()
    invitation.redemption_count += 1
    session.add(
        AccessGrant(
            user_id=user.id,
            invitation_id=invitation.id,
            limits=dict(invitation.limits),
            credits=invitation.credits,
            unlimited=invitation.unlimited,
            status="active",
        )
    )
    if invitation.credits is not None:
        session.add(
            CreditLedgerEntry(
                user_id=user.id,
                change="join",
                amount=invitation.credits,
                balance=invitation.credits,
                subject=f"invitation:{invitation.id}",
                created_at=_now(),
            )
        )
    await session.flush()


def act_for(session: AsyncSession, *, user_id: UUID, settings: Settings) -> None:
    """Charge like the person's own request would, for work a worker starts after it ended.

    A press that finds the queue full is started later (ADR 0068), and must cost what its card
    said. Operators have no grant to charge, so only open mode and the prices need carrying.
    """
    session.info[_REQUEST_ACCESS] = RequestAccess(
        user_id, settings.access_mode == "open", dict(settings.access_credit_prices)
    )


async def charge_usage(
    session: AsyncSession,
    *,
    user_id: UUID,
    item: str,
    units: int,
    quantity: int | None = None,
    subject: str | None = None,
) -> None:
    """Admit ``units`` of ``item`` for the user: check the caps, then spend the credits.

    ``units`` count against the kind's caps (images, lines, turns, builds, trainings);
    ``quantity`` (default ``units``) multiplies the price, e.g. 100-step training blocks.
    People without a grant, operators and open mode are not charged.
    """
    request = session.info.get(_REQUEST_ACCESS)
    if not isinstance(request, RequestAccess) or request.user_id != user_id:
        request = None
    if request is not None and request.exempt:
        return
    price = resolve_prices(request.prices if request else None)[item]
    if units <= 0:
        return
    grant = await session.scalar(
        select(AccessGrant).where(AccessGrant.user_id == user_id).with_for_update()
    )
    if grant is None:
        return
    if grant.status != "active":
        raise access_required()
    now = _now()
    quantity = units if quantity is None else quantity
    needed = price.credits * quantity
    if not grant.unlimited:
        used_day, used_total = (
            await session.execute(
                select(
                    func.coalesce(
                        func.sum(
                            case(
                                (UsageCharge.created_at >= now - _WINDOW, UsageCharge.units),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(func.sum(UsageCharge.units), 0),
                ).where(UsageCharge.user_id == user_id, UsageCharge.kind == price.kind)
            )
        ).one()
        problem = limit_problem(grant.limits, price.kind, units, int(used_day), int(used_total))
        if problem is not None:
            raise DomainError(429, "Usage limit reached", problem, "usage-limit")
        if grant.credits is not None and needed > grant.credits:
            raise DomainError(
                402,
                "Out of credits",
                credit_problem(price, quantity=quantity, balance=grant.credits),
                "out-of-credits",
                [{"credits_needed": needed, "credits_left": grant.credits}],
            )
    session.add(
        UsageCharge(
            user_id=user_id,
            kind=price.kind,
            units=units,
            item=item,
            subject=subject,
            created_at=now,
        )
    )
    if not grant.unlimited and grant.credits is not None and needed > 0:
        grant.credits -= needed
        session.add(
            CreditLedgerEntry(
                user_id=user_id,
                change="charge",
                amount=-needed,
                balance=grant.credits,
                item=item,
                quantity=quantity,
                subject=subject,
                created_at=now,
            )
        )
    await session.flush()


async def create_invitation(
    session: AsyncSession,
    *,
    kind: str,
    label: str,
    email: str | None,
    max_redemptions: int,
    limits: dict[str, Any] | None,
    expires_at: datetime | None,
    created_by: UUID,
    settings: Settings,
    credits: int | None = None,
    unlimited: bool = False,
) -> tuple[AccessInvitation, str | None]:
    """Create an invitation; a key invitation's key is returned once and never stored.

    An unlimited invitation carries no credits and no caps, so a grant made from it
    fails closed if an operator later turns unlimited off.
    """
    label = label.strip()
    if not label or len(label) > 120:
        raise _invalid("Give the invitation a label of up to 120 characters.")
    try:
        granted = clean_limits(settings.access_default_limits if limits is None else limits)
    except ValueError as error:
        raise _invalid(str(error)) from None
    credits = settings.access_default_credits if credits is None else credits
    if not 0 <= credits <= MAX_CREDITS:
        raise _invalid(f"Credits must be between 0 and {MAX_CREDITS}.")
    if unlimited:
        granted, credits = {}, 0
    expires_at = _aware(expires_at)
    if expires_at is not None and expires_at <= _now():
        raise _invalid("Choose an expiry in the future.")
    key: str | None = None
    if kind == "key":
        if not 1 <= max_redemptions <= 1000:
            raise _invalid("A key can be redeemed between 1 and 1000 times.")
        key = new_key()
        invitation = AccessInvitation(
            kind="key",
            label=label,
            key_sha256=key_hash(key),
            key_hint=key[-4:],
            max_redemptions=max_redemptions,
            limits=granted,
            credits=credits,
            unlimited=unlimited,
            expires_at=expires_at,
            created_by_user_id=created_by,
        )
    elif kind == "email":
        address = (email or "").strip().lower()
        if not _EMAIL.match(address) or len(address) > 320:
            raise _invalid("Enter the email address to invite.")
        invitation = AccessInvitation(
            kind="email",
            label=label,
            email=address,
            max_redemptions=1,
            limits=granted,
            credits=credits,
            unlimited=unlimited,
            expires_at=expires_at,
            created_by_user_id=created_by,
        )
    else:
        raise _invalid("Choose a key or an email invitation.")
    session.add(invitation)
    await session.flush()
    await session.refresh(invitation)
    return invitation, key


def _invalid(detail: str) -> DomainError:
    return DomainError(422, "Invalid invitation", detail, "invalid-invitation")


async def list_invitations(session: AsyncSession) -> list[AccessInvitation]:
    query = select(AccessInvitation).order_by(AccessInvitation.created_at.desc()).limit(200)
    return list((await session.scalars(query)).all())


async def revoke_invitation(session: AsyncSession, invitation_id: UUID) -> AccessInvitation:
    invitation = await session.scalar(
        select(AccessInvitation).where(AccessInvitation.id == invitation_id).with_for_update()
    )
    if invitation is None:
        raise NotFoundError("Invitation was not found.")
    if invitation.revoked_at is None:
        invitation.revoked_at = _now()
        await session.flush()
    return invitation


@dataclass(frozen=True, slots=True)
class GrantRow:
    grant: AccessGrant
    user: User
    invitation_label: str | None
    usage: dict[str, dict[str, int]]


async def list_grants(session: AsyncSession) -> list[GrantRow]:
    rows = (
        await session.execute(
            select(AccessGrant, User, AccessInvitation.label)
            .join(User, User.id == AccessGrant.user_id)
            .outerjoin(AccessInvitation, AccessInvitation.id == AccessGrant.invitation_id)
            .order_by(AccessGrant.created_at.desc())
            .limit(500)
        )
    ).all()
    return [
        GrantRow(grant, user, label, await usage_summary(session, user.id))
        for grant, user, label in rows
    ]


async def set_grant_status(session: AsyncSession, grant_id: UUID, status: str) -> AccessGrant:
    grant = await session.scalar(
        select(AccessGrant).where(AccessGrant.id == grant_id).with_for_update()
    )
    if grant is None:
        raise NotFoundError("Access grant was not found.")
    grant.status = status
    grant.suspended_at = _now() if status == "suspended" else None
    await session.flush()
    return grant


async def _locked_grant(session: AsyncSession, grant_id: UUID) -> AccessGrant:
    grant = await session.scalar(
        select(AccessGrant).where(AccessGrant.id == grant_id).with_for_update()
    )
    if grant is None:
        raise NotFoundError("Access grant was not found.")
    return grant


def _credit_error(detail: str) -> DomainError:
    return DomainError(422, "Invalid credit change", detail, "invalid-credit-change")


async def adjust_credits(
    session: AsyncSession,
    grant_id: UUID,
    *,
    change: str,
    amount: int,
    note: str | None,
    actor_id: UUID,
) -> AccessGrant:
    """An operator adds, removes or sets a person's credits, recorded in the ledger."""
    grant = await _locked_grant(session, grant_id)
    note = (note or "").strip()[:300] or None
    if change not in ("add", "remove", "set"):
        raise _credit_error("Choose add, remove or set.")
    if not 0 <= amount <= MAX_CREDITS:
        raise _credit_error(f"Enter between 0 and {MAX_CREDITS} credits.")
    if change != "set" and amount < 1:
        raise _credit_error("Enter at least 1 credit.")
    if grant.credits is None and change != "set":
        raise DomainError(
            409,
            "No credit balance",
            "This person joined before credits. Set a balance first.",
            "credits-not-set",
        )
    before = grant.credits or 0
    if change == "add":
        after = before + amount
        if after > MAX_CREDITS:
            raise _credit_error(f"A balance can be at most {MAX_CREDITS} credits.")
    elif change == "remove":
        if amount > before:
            raise _credit_error(
                f"They have {before} credits. Set the balance to 0 to remove them all."
            )
        after = before - amount
    else:
        after = amount
    grant.credits = after
    session.add(
        CreditLedgerEntry(
            user_id=grant.user_id,
            change=change,
            amount=after - before,
            balance=after,
            actor_user_id=actor_id,
            note=note,
            created_at=_now(),
        )
    )
    await session.flush()
    return grant


async def set_unlimited(
    session: AsyncSession, grant_id: UUID, *, unlimited: bool, note: str | None, actor_id: UUID
) -> AccessGrant:
    """Turn unlimited on or off; the balance is kept for when it is off."""
    grant = await _locked_grant(session, grant_id)
    if grant.unlimited == unlimited:
        return grant
    grant.unlimited = unlimited
    session.add(
        CreditLedgerEntry(
            user_id=grant.user_id,
            change="unlimited" if unlimited else "limited",
            amount=0,
            balance=grant.credits,
            actor_user_id=actor_id,
            note=(note or "").strip()[:300] or None,
            created_at=_now(),
        )
    )
    await session.flush()
    return grant


@dataclass(frozen=True, slots=True)
class LedgerRow:
    entry: CreditLedgerEntry
    actor_email: str | None


async def credit_history(session: AsyncSession, user_id: UUID, limit: int = 200) -> list[LedgerRow]:
    """A person's credit changes, newest first."""
    rows = (
        await session.execute(
            select(CreditLedgerEntry, User.email)
            .outerjoin(User, User.id == CreditLedgerEntry.actor_user_id)
            .where(CreditLedgerEntry.user_id == user_id)
            .order_by(CreditLedgerEntry.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [LedgerRow(entry, email) for entry, email in rows]


async def grant_owner(session: AsyncSession, grant_id: UUID) -> UUID:
    user_id = await session.scalar(select(AccessGrant.user_id).where(AccessGrant.id == grant_id))
    if user_id is None:
        raise NotFoundError("Access grant was not found.")
    return user_id
