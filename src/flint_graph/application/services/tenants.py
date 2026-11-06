from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.infrastructure.db.models import Tenant


async def create_tenant(session: AsyncSession, *, name: str) -> Tenant:
    """Names are not unique across the server; see ``require_workspace_name_free``."""
    tenant = Tenant(name=name)
    session.add(tenant)
    await session.flush()
    await session.refresh(tenant)
    return tenant
