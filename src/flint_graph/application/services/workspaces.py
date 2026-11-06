from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.authz import (
    AuthenticatedPrincipal,
    add_workspace_member,
    upsert_user_from_principal,
)
from flint_graph.application.services.tenants import create_tenant
from flint_graph.domain.enums import WorkspaceMembershipStatus, WorkspaceRole
from flint_graph.domain.errors import ConflictError
from flint_graph.infrastructure.db.models import Tenant, User, WorkspaceMembership


@dataclass(frozen=True, slots=True)
class WorkspaceSummary:
    id: UUID
    name: str
    role: WorkspaceRole


@dataclass(frozen=True, slots=True)
class WorkspaceMemberSummary:
    user_id: UUID
    email: str | None
    display_name: str | None
    role: WorkspaceRole


async def require_workspace_name_free(session: AsyncSession, *, name: str, user_id: UUID) -> None:
    """A person's workspaces have different names, whatever anyone else calls theirs.

    Only the person's own active workspaces are compared, so a refusal can never reveal that
    someone else has a workspace by that name.
    """
    # Serializes one person's creations, so a double click cannot make two.
    await session.scalar(select(User.id).where(User.id == user_id).with_for_update(key_share=True))
    taken = await session.scalar(
        select(Tenant.id)
        .join(WorkspaceMembership, WorkspaceMembership.tenant_id == Tenant.id)
        .where(
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.status == WorkspaceMembershipStatus.ACTIVE,
            func.lower(Tenant.name) == func.lower(name),
        )
        .limit(1)
    )
    if taken is not None:
        raise ConflictError(f"You already have a workspace called '{name}'.")


async def create_workspace_for_user(
    session: AsyncSession,
    *,
    name: str,
    user_id: UUID,
) -> WorkspaceSummary:
    await require_workspace_name_free(session, name=name, user_id=user_id)
    tenant = await create_tenant(session, name=name)
    membership = await add_workspace_member(
        session,
        tenant_id=tenant.id,
        user_id=user_id,
        role=WorkspaceRole.OWNER,
    )
    return WorkspaceSummary(id=tenant.id, name=tenant.name, role=membership.role)


async def list_workspaces_for_user(
    session: AsyncSession,
    *,
    user_id: UUID,
) -> list[WorkspaceSummary]:
    rows = await session.execute(
        select(Tenant, WorkspaceMembership)
        .join(WorkspaceMembership, WorkspaceMembership.tenant_id == Tenant.id)
        .where(
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.status == WorkspaceMembershipStatus.ACTIVE,
        )
        .order_by(Tenant.name, Tenant.id)
    )
    return [
        WorkspaceSummary(id=tenant.id, name=tenant.name, role=membership.role)
        for tenant, membership in rows.all()
    ]


async def add_workspace_member_by_identity(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    oidc_issuer: str,
    oidc_subject: str,
    email: str | None,
    display_name: str | None,
    role: WorkspaceRole,
) -> WorkspaceMemberSummary:
    user = await upsert_user_from_principal(
        session,
        AuthenticatedPrincipal(
            issuer=oidc_issuer,
            subject=oidc_subject,
            email=email,
            display_name=display_name,
            claims={"provisioned": True},
        ),
    )
    membership = await add_workspace_member(
        session,
        tenant_id=tenant_id,
        user_id=user.id,
        role=role,
    )
    return WorkspaceMemberSummary(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=membership.role,
    )
