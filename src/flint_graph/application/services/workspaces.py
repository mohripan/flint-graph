from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.authz import (
    AuthenticatedPrincipal,
    add_workspace_member,
    upsert_user_from_principal,
)
from flint_graph.application.services.tenants import create_tenant
from flint_graph.domain.enums import WorkspaceMembershipStatus, WorkspaceRole
from flint_graph.infrastructure.db.models import Tenant, WorkspaceMembership


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


async def create_workspace_for_user(
    session: AsyncSession,
    *,
    name: str,
    user_id: UUID,
) -> WorkspaceSummary:
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
        .order_by(Tenant.name)
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
