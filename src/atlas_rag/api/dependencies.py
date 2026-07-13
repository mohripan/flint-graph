from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas_rag.config import Settings, get_settings
from atlas_rag.domain.errors import NotFoundError
from atlas_rag.infrastructure.db.models import Tenant
from atlas_rag.infrastructure.db.session import get_session
from atlas_rag.infrastructure.neo4j import Neo4jClient, create_neo4j_client
from atlas_rag.infrastructure.object_store import ObjectStore, create_object_store
from atlas_rag.infrastructure.url_fetcher import HTTPURLFetcher, URLFetcher

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


async def get_tenant_id(
    session: SessionDep,
    x_tenant_id: Annotated[UUID, Header(alias="X-Tenant-ID")],
) -> UUID:
    exists = await session.scalar(select(Tenant.id).where(Tenant.id == x_tenant_id))
    if exists is None:
        raise NotFoundError(f"Tenant '{x_tenant_id}' was not found.")
    return x_tenant_id


TenantIdDep = Annotated[UUID, Depends(get_tenant_id)]


def get_object_store(settings: SettingsDep) -> ObjectStore:
    return create_object_store(settings)


ObjectStoreDep = Annotated[ObjectStore, Depends(get_object_store)]


def get_url_fetcher(settings: SettingsDep) -> URLFetcher:
    return HTTPURLFetcher(
        timeout_seconds=settings.intake_url_timeout_seconds,
        max_bytes=settings.intake_max_source_bytes,
    )


URLFetcherDep = Annotated[URLFetcher, Depends(get_url_fetcher)]


async def get_neo4j_client(settings: SettingsDep) -> AsyncIterator[Neo4jClient]:
    client = create_neo4j_client(settings)
    try:
        yield client
    finally:
        await client.close()


Neo4jClientDep = Annotated[Neo4jClient, Depends(get_neo4j_client)]
