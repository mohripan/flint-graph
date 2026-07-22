from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

import httpx
from anthropic import AsyncAnthropic
from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.embeddings import EmbeddingModel
from flint_graph.application.query_orchestration import AnswerGenerator, SupportChecker
from flint_graph.config import Settings, get_settings
from flint_graph.domain.errors import NotFoundError
from flint_graph.infrastructure.answer_generator_factory import (
    answer_generator_base_url,
    create_answer_generator,
    create_support_checker,
)
from flint_graph.infrastructure.db.models import Tenant
from flint_graph.infrastructure.db.session import get_session
from flint_graph.infrastructure.embedding_factory import (
    create_embedding_model,
    embedding_base_url,
)
from flint_graph.infrastructure.neo4j import Neo4jClient, create_neo4j_client
from flint_graph.infrastructure.object_store import ObjectStore, create_object_store
from flint_graph.infrastructure.opensearch import OpenSearchClient, create_opensearch_client
from flint_graph.infrastructure.temporal import (
    TemporalIndexBackfillWorkflowStarter,
    connect_temporal,
)
from flint_graph.infrastructure.url_fetcher import HTTPURLFetcher, URLFetcher

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


async def get_opensearch_client(settings: SettingsDep) -> AsyncIterator[OpenSearchClient]:
    client = create_opensearch_client(settings)
    try:
        yield client
    finally:
        await client.close()


OpenSearchClientDep = Annotated[OpenSearchClient, Depends(get_opensearch_client)]


async def get_embedding_model(settings: SettingsDep) -> AsyncIterator[EmbeddingModel]:
    async with httpx.AsyncClient(base_url=embedding_base_url(settings)) as http_client:
        yield create_embedding_model(settings, http_client=http_client)


EmbeddingModelDep = Annotated[EmbeddingModel, Depends(get_embedding_model)]


async def get_answer_generator(settings: SettingsDep) -> AsyncIterator[AnswerGenerator]:
    if settings.query_answer_provider == "anthropic":
        async with AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.query_answer_timeout_seconds,
        ) as anthropic_client:
            yield create_answer_generator(settings, anthropic_client=anthropic_client)
        return
    async with httpx.AsyncClient(base_url=answer_generator_base_url(settings)) as http_client:
        yield create_answer_generator(settings, http_client=http_client)


AnswerGeneratorDep = Annotated[AnswerGenerator, Depends(get_answer_generator)]


async def get_support_checker(settings: SettingsDep) -> AsyncIterator[SupportChecker]:
    if settings.query_support_provider == "anthropic":
        async with AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.query_answer_timeout_seconds,
        ) as anthropic_client:
            yield create_support_checker(settings, anthropic_client=anthropic_client)
        return
    if settings.query_support_provider == "ollama":
        async with httpx.AsyncClient(base_url=answer_generator_base_url(settings)) as http_client:
            yield create_support_checker(settings, http_client=http_client)
        return
    yield create_support_checker(settings)


SupportCheckerDep = Annotated[SupportChecker, Depends(get_support_checker)]


async def get_index_backfill_workflow_starter(
    settings: SettingsDep,
) -> TemporalIndexBackfillWorkflowStarter:
    client = await connect_temporal(settings)
    return TemporalIndexBackfillWorkflowStarter(
        client,
        task_queue=settings.temporal_task_queue,
    )


IndexBackfillWorkflowStarterDep = Annotated[
    TemporalIndexBackfillWorkflowStarter,
    Depends(get_index_backfill_workflow_starter),
]
