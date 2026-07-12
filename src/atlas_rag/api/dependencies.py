from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.domain.errors import NotFoundError
from atlas_rag.infrastructure.db.models import Tenant
from atlas_rag.infrastructure.db.session import get_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_tenant_id(
    session: SessionDep,
    x_tenant_id: Annotated[UUID, Header(alias="X-Tenant-ID")],
) -> UUID:
    exists = await session.scalar(select(Tenant.id).where(Tenant.id == x_tenant_id))
    if exists is None:
        raise NotFoundError(f"Tenant '{x_tenant_id}' was not found.")
    return x_tenant_id


TenantIdDep = Annotated[UUID, Depends(get_tenant_id)]