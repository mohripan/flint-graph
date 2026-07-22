from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.domain.enums import WorkspaceMembershipStatus, WorkspaceRole
from flint_graph.domain.errors import ForbiddenError
from flint_graph.infrastructure.db.models import User, WorkspaceMembership


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    issuer: str
    subject: str
    email: str | None
    display_name: str | None
    claims: dict[str, object]


async def upsert_user_from_principal(
    session: AsyncSession,
    principal: AuthenticatedPrincipal,
) -> User:
    existing = await session.scalar(
        select(User).where(
            User.oidc_issuer == principal.issuer,
            User.oidc_subject == principal.subject,
        )
    )
    now = datetime.now(UTC)
    if existing is not None:
        existing.email = principal.email
        existing.display_name = principal.display_name
        existing.claims = dict(principal.claims)
        existing.last_login_at = now
        await session.flush()
        return existing

    user = User(
        oidc_issuer=principal.issuer,
        oidc_subject=principal.subject,
        email=principal.email,
        display_name=principal.display_name,
        claims=dict(principal.claims),
        last_login_at=now,
    )
    try:
        async with session.begin_nested():
            session.add(user)
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(
            select(User).where(
                User.oidc_issuer == principal.issuer,
                User.oidc_subject == principal.subject,
            )
        )
        if existing is None:
            raise
        existing.email = principal.email
        existing.display_name = principal.display_name
        existing.claims = dict(principal.claims)
        existing.last_login_at = now
        await session.flush()
        return cast(User, existing)
    await session.refresh(user)
    return user


async def add_workspace_member(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    role: WorkspaceRole,
) -> WorkspaceMembership:
    existing = await session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.tenant_id == tenant_id,
            WorkspaceMembership.user_id == user_id,
        )
    )
    if existing is not None:
        existing.role = role
        existing.status = WorkspaceMembershipStatus.ACTIVE
        await session.flush()
        return existing

    membership = WorkspaceMembership(
        tenant_id=tenant_id,
        user_id=user_id,
        role=role,
        status=WorkspaceMembershipStatus.ACTIVE,
    )
    session.add(membership)
    await session.flush()
    return membership


async def get_workspace_role(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
) -> WorkspaceRole | None:
    role = await session.scalar(
        select(WorkspaceMembership.role).where(
            WorkspaceMembership.tenant_id == tenant_id,
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.status == WorkspaceMembershipStatus.ACTIVE,
        )
    )
    return role


def require_workspace_role(
    role: WorkspaceRole | None,
    *,
    allowed: set[WorkspaceRole],
) -> None:
    if role is None or role not in allowed:
        raise ForbiddenError("The authenticated user is not allowed to perform this action.")


def role_at_least(role: WorkspaceRole) -> set[WorkspaceRole]:
    match role:
        case WorkspaceRole.VIEWER:
            return {
                WorkspaceRole.VIEWER,
                WorkspaceRole.MEMBER,
                WorkspaceRole.ADMIN,
                WorkspaceRole.OWNER,
            }
        case WorkspaceRole.MEMBER:
            return {WorkspaceRole.MEMBER, WorkspaceRole.ADMIN, WorkspaceRole.OWNER}
        case WorkspaceRole.ADMIN:
            return {WorkspaceRole.ADMIN, WorkspaceRole.OWNER}
        case WorkspaceRole.OWNER:
            return {WorkspaceRole.OWNER}
