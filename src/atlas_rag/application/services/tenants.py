from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.domain.errors import ConflictError
from atlas_rag.infrastructure.db.models import Tenant


async def create_tenant(session: AsyncSession, *, name: str) -> Tenant:
    tenant = Tenant(name=name)
    try:
        async with session.begin_nested():
            session.add(tenant)
            await session.flush()
    except IntegrityError as exc:
        existing = await session.scalar(select(Tenant).where(Tenant.name == name))
        if existing is not None:
            raise ConflictError(f"A tenant named '{name}' already exists.") from exc
        raise
    await session.refresh(tenant)
    return tenant