"""Joining an invite-only Studio, credits, and the operator's invitations (ADR 0058, 0059).

These routes take the signed-in user without the invite-only check: a person needs
them to find out whether they have access and to join.
"""

from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.api.access_schemas import (
    AccessStatus,
    CreditChange,
    CreditEntryResponse,
    CreditHistory,
    GrantList,
    GrantResponse,
    InvitationCreate,
    InvitationCreated,
    InvitationList,
    InvitationResponse,
    JoinRequest,
    PriceResponse,
    UnlimitedChange,
)
from flint_graph.api.dependencies import (
    AccessOperatorDep,
    CurrentUser,
    SessionDep,
    SettingsDep,
    SignedInUserDep,
)
from flint_graph.api.routes.narrative import _persist
from flint_graph.application.credit_prices import assistant_item
from flint_graph.application.services.access import (
    GrantRow,
    LedgerRow,
    access_state,
    adjust_credits,
    create_invitation,
    credit_history,
    grant_owner,
    join,
    list_grants,
    list_invitations,
    revoke_invitation,
    set_grant_status,
    set_unlimited,
)
from flint_graph.config import Settings

router = APIRouter(prefix="/v1/access", tags=["access"])
admin_router = APIRouter(prefix="/v1/admin/access", tags=["access"])


async def _status(session: AsyncSession, current: CurrentUser, settings: Settings) -> AccessStatus:
    state = await access_state(session, current.user, current.principal, settings)
    provider = settings.narrative_assistant_provider
    return AccessStatus(
        mode=state.mode,
        has_access=state.has_access,
        is_admin=state.is_admin,
        status=state.status,
        email=current.user.email,
        display_name=current.user.display_name,
        limits=state.limits,
        usage=state.usage,
        email_invitation=state.email_invitation,
        credits=state.credits,
        unlimited=state.unlimited,
        keeps_going=state.keeps_going,
        prices={
            item_id: PriceResponse(
                credits=item.credits, kind=item.kind, label=item.label, unit=item.unit, per=item.per
            )
            for item_id, item in state.prices.items()
        },
        assistant_item=assistant_item(provider) if provider and provider != "disabled" else None,
    )


def _history(rows: list[LedgerRow]) -> CreditHistory:
    return CreditHistory(
        entries=[
            CreditEntryResponse(
                id=row.entry.id,
                change=row.entry.change,
                amount=row.entry.amount,
                balance=row.entry.balance,
                item=row.entry.item,
                quantity=row.entry.quantity,
                subject=row.entry.subject,
                note=row.entry.note,
                actor_email=row.actor_email,
                created_at=row.entry.created_at,
            )
            for row in rows
        ]
    )


@router.get("/me", response_model=AccessStatus)
async def access_me_endpoint(
    current: SignedInUserDep, session: SessionDep, settings: SettingsDep
) -> AccessStatus:
    status = await _status(session, current, settings)
    await session.commit()  # keeps the user row upserted by sign-in
    return status


@router.get("/credits", response_model=CreditHistory)
async def my_credits_endpoint(current: SignedInUserDep, session: SessionDep) -> CreditHistory:
    return _history(await credit_history(session, current.user.id, limit=100))


@router.post("/join", response_model=AccessStatus)
async def join_endpoint(
    payload: JoinRequest, current: SignedInUserDep, session: SessionDep, settings: SettingsDep
) -> AccessStatus:
    key = (payload.key or "").strip() or None
    await _persist(
        session,
        join(session, user=current.user, principal=current.principal, settings=settings, key=key),
    )
    return await _status(session, current, settings)


@admin_router.get("/invitations", response_model=InvitationList)
async def list_invitations_endpoint(
    _: AccessOperatorDep, session: SessionDep, settings: SettingsDep
) -> InvitationList:
    rows = await list_invitations(session)
    return InvitationList(
        invitations=[InvitationResponse.model_validate(row) for row in rows],
        default_limits=settings.access_default_limits,
        default_credits=settings.access_default_credits,
    )


@admin_router.post("/invitations", response_model=InvitationCreated, status_code=201)
async def create_invitation_endpoint(
    payload: InvitationCreate,
    operator: AccessOperatorDep,
    session: SessionDep,
    settings: SettingsDep,
) -> InvitationCreated:
    invitation, key = await _persist(
        session,
        create_invitation(
            session,
            kind=payload.kind,
            label=payload.label,
            email=payload.email,
            max_redemptions=payload.max_redemptions,
            limits=payload.limits,
            expires_at=payload.expires_at,
            created_by=operator.user.id,
            settings=settings,
            credits=payload.credits,
            unlimited=payload.unlimited,
        ),
    )
    base = (settings.public_base_url or "").rstrip("/")
    link = f"{base}/join" + (f"?key={quote(key)}" if key else "")
    return InvitationCreated(
        invitation=InvitationResponse.model_validate(invitation), key=key, link=link
    )


@admin_router.post("/invitations/{invitation_id}/revoke", response_model=InvitationResponse)
async def revoke_invitation_endpoint(
    invitation_id: UUID, _: AccessOperatorDep, session: SessionDep
) -> InvitationResponse:
    invitation = await _persist(session, revoke_invitation(session, invitation_id))
    return InvitationResponse.model_validate(invitation)


def _grant(row: GrantRow) -> GrantResponse:
    return GrantResponse(
        id=row.grant.id,
        user_id=row.user.id,
        email=row.user.email,
        display_name=row.user.display_name,
        status=row.grant.status,
        invitation_label=row.invitation_label,
        limits=row.grant.limits,
        usage=row.usage,
        credits=row.grant.credits,
        unlimited=row.grant.unlimited,
        created_at=row.grant.created_at,
    )


@admin_router.get("/grants", response_model=GrantList)
async def list_grants_endpoint(_: AccessOperatorDep, session: SessionDep) -> GrantList:
    return GrantList(grants=[_grant(row) for row in await list_grants(session)])


async def _reload(session: AsyncSession, grant_id: UUID) -> GrantResponse:
    return _grant(next(row for row in await list_grants(session) if row.grant.id == grant_id))


@admin_router.post("/grants/{grant_id}/suspend", response_model=GrantResponse)
async def suspend_grant_endpoint(
    grant_id: UUID, _: AccessOperatorDep, session: SessionDep
) -> GrantResponse:
    await _persist(session, set_grant_status(session, grant_id, "suspended"))
    return await _reload(session, grant_id)


@admin_router.post("/grants/{grant_id}/resume", response_model=GrantResponse)
async def resume_grant_endpoint(
    grant_id: UUID, _: AccessOperatorDep, session: SessionDep
) -> GrantResponse:
    await _persist(session, set_grant_status(session, grant_id, "active"))
    return await _reload(session, grant_id)


@admin_router.post("/grants/{grant_id}/credits", response_model=GrantResponse)
async def change_credits_endpoint(
    grant_id: UUID, payload: CreditChange, operator: AccessOperatorDep, session: SessionDep
) -> GrantResponse:
    await _persist(
        session,
        adjust_credits(
            session,
            grant_id,
            change=payload.change,
            amount=payload.amount,
            note=payload.note,
            actor_id=operator.user.id,
        ),
    )
    return await _reload(session, grant_id)


@admin_router.post("/grants/{grant_id}/unlimited", response_model=GrantResponse)
async def unlimited_endpoint(
    grant_id: UUID, payload: UnlimitedChange, operator: AccessOperatorDep, session: SessionDep
) -> GrantResponse:
    await _persist(
        session,
        set_unlimited(
            session,
            grant_id,
            unlimited=payload.unlimited,
            note=payload.note,
            actor_id=operator.user.id,
        ),
    )
    return await _reload(session, grant_id)


@admin_router.get("/grants/{grant_id}/credits", response_model=CreditHistory)
async def grant_credits_endpoint(
    grant_id: UUID, _: AccessOperatorDep, session: SessionDep
) -> CreditHistory:
    return _history(await credit_history(session, await grant_owner(session, grant_id)))
