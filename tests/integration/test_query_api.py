from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import atlas_rag.api.dependencies as dependencies
from atlas_rag.application.query_orchestration import (
    AnswerCitation,
    AnswerGenerationRequest,
    GeneratedAnswer,
)
from atlas_rag.application.services.retrieval_index_versions import (
    RetrievalIndexVersionSpec,
    activate_retrieval_index_version,
    create_retrieval_index_version,
)
from atlas_rag.domain.enums import RetrievalIndexScope
from atlas_rag.infrastructure.db.base import Base
from atlas_rag.infrastructure.db.models import Tenant
from atlas_rag.infrastructure.db.session import get_session
from atlas_rag.main import app


class QueryOpenSearchClient:
    def __init__(self) -> None:
        self.searches: list[tuple[str, dict[str, Any]]] = []

    async def search(self, *, index_name: str, body: dict[str, Any]) -> list[dict[str, Any]]:
        self.searches.append((index_name, body))
        tenant_id = body["query"]["bool"]["filter"][0]["term"]["tenant_id"]
        return [
            {
                "id": "lexical-hit-1",
                "score": 3.0,
                "source": {
                    "tenant_id": tenant_id,
                    "document_id": "11111111-1111-4111-8111-111111111111",
                    "document_version_id": "22222222-2222-4222-8222-222222222222",
                    "chunk_id": "chunk-acme",
                    "chunk_hash": "sha256:chunk-acme",
                    "title": "Acme Brief",
                    "text": "Acme Corporation is headquartered in Berlin.",
                    "heading_path": ["Overview"],
                    "page_start": 1,
                    "page_end": 1,
                    "source_uri": "s3://atlas/acme.txt",
                    "metadata": {"source_type": "upload"},
                },
            }
        ]

    async def close(self) -> None:
        return None


class QueryNeo4jClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        params = parameters or {}
        self.calls.append((query, params))
        return [
            {
                "score": 0.8,
                "node": {
                    "tenant_id": str(params["tenant_id"]),
                    "document_id": "11111111-1111-4111-8111-111111111111",
                    "document_version_id": "22222222-2222-4222-8222-222222222222",
                    "chunk_id": "chunk-acme",
                    "chunk_hash": "sha256:chunk-acme",
                    "retrieval_index_version_id": str(params["retrieval_index_version_id"]),
                    "text_preview": "Acme Corporation is headquartered in Berlin.",
                    "metadata_json": '{"source_type":"upload"}',
                },
            }
        ]

    async def close(self) -> None:
        return None


class QueryAnswerGenerator:
    def __init__(self) -> None:
        self.requests: list[AnswerGenerationRequest] = []

    async def generate(self, request: AnswerGenerationRequest) -> GeneratedAnswer:
        self.requests.append(request)
        record = request.context_pack.records[0]
        return GeneratedAnswer(
            text="Provider-backed answer. [c1]",
            citations=[
                AnswerCitation(
                    citation_id=record.citation_id,
                    context_id=record.context_id,
                    marker=f"[{record.citation_id}]",
                    source_ids=record.source_ids,
                )
            ],
            metadata={"provider": "test"},
        )


@pytest_asyncio.fixture
async def query_api_env() -> AsyncIterator[
    tuple[
        httpx.AsyncClient,
        async_sessionmaker[AsyncSession],
        QueryOpenSearchClient,
        QueryNeo4jClient,
    ]
]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    opensearch = QueryOpenSearchClient()
    neo4j = QueryNeo4jClient()
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[dependencies.get_opensearch_client] = lambda: opensearch
    app.dependency_overrides[dependencies.get_neo4j_client] = lambda: neo4j
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, session_factory, opensearch, neo4j
    app.dependency_overrides.clear()
    await engine.dispose()


def _headers(tenant_id: UUID) -> dict[str, str]:
    return {"X-Tenant-ID": str(tenant_id)}


def _index_spec() -> RetrievalIndexVersionSpec:
    return RetrievalIndexVersionSpec(
        embedding_provider="deterministic",
        embedding_model="query-api-v1",
        vector_dimension=4,
        embedding_config_hash="sha256:query-api-v1",
        chunking_schema_version="1",
        chunking_config_hash="sha256:chunking",
        lexical_schema_version="1",
        neo4j_vector_index_name="atlas_chunks_query_api_v1",
        neo4j_vector_property_name="embedding",
        opensearch_index_name="atlas_chunks_query_api_v1",
        opensearch_alias_name="atlas_chunks_active",
    )


async def _tenant_with_active_index(session: AsyncSession) -> tuple[Tenant, UUID]:
    tenant = Tenant(name="query-api")
    session.add(tenant)
    await session.flush()
    version = await create_retrieval_index_version(
        session,
        scope=RetrievalIndexScope.TENANT,
        tenant_id=tenant.id,
        spec=_index_spec(),
    )
    active = await activate_retrieval_index_version(session, version_id=version.id)
    await session.commit()
    return tenant, active.id


def _sse_event_types(body: str) -> list[str]:
    return [
        line.removeprefix("event: ")
        for line in body.splitlines()
        if line.startswith("event: ")
    ]


@pytest.mark.asyncio
async def test_query_run_api_streams_execution_and_persists_inspection_records(
    query_api_env: tuple[
        httpx.AsyncClient,
        async_sessionmaker[AsyncSession],
        QueryOpenSearchClient,
        QueryNeo4jClient,
    ],
) -> None:
    client, session_factory, opensearch, neo4j = query_api_env
    async with session_factory() as session:
        tenant, index_version_id = await _tenant_with_active_index(session)
        tenant_id = tenant.id

    created = await client.post(
        "/v1/query-runs",
        headers=_headers(tenant_id),
        json={
            "query": "Where is Acme Corporation headquartered?",
            "retrieval_index_version_id": str(index_version_id),
        },
    )
    assert created.status_code == 201
    created_body = created.json()
    assert created_body["status"] == "queued"
    query_run_id = created_body["id"]

    stream = await client.get(
        f"/v1/query-runs/{query_run_id}/events/stream",
        headers=_headers(tenant_id),
    )
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    event_types = _sse_event_types(stream.text)
    assert event_types == [
        "query.started",
        "query.classified",
        "entities.linked",
        "retrieval.started",
        "retrieval.progress",
        "retrieval.progress",
        "retrieval.completed",
        "fusion.completed",
        "rerank.completed",
        "context.packed",
        "answer.delta",
        "answer.citation",
        "query.completed",
    ], event_types

    inspected = await client.get(
        f"/v1/query-runs/{query_run_id}",
        headers=_headers(tenant_id),
    )
    assert inspected.status_code == 200
    inspected_body = inspected.json()
    assert inspected_body["status"] == "completed"
    assert inspected_body["answer_text"] == "Acme Corporation is headquartered in Berlin. [c1]"
    assert inspected_body["answer_citations"] == [
        {
            "citation_id": "c1",
            "context_id": "ctx-0001",
            "marker": "[c1]",
            "source_ids": {"chunk_id": "chunk-acme"},
        }
    ]
    assert inspected_body["candidate_count"] == 2
    assert inspected_body["context_token_count"] == 6

    events = await client.get(
        f"/v1/query-runs/{query_run_id}/events",
        headers=_headers(tenant_id),
    )
    assert events.status_code == 200
    event_rows = events.json()
    assert [event["event_type"] for event in event_rows] == event_types
    assert [event["sequence"] for event in event_rows] == list(range(1, len(event_rows) + 1))
    assert opensearch.searches
    assert neo4j.calls


@pytest.mark.asyncio
async def test_query_run_api_stream_uses_answer_generator_dependency(
    query_api_env: tuple[
        httpx.AsyncClient,
        async_sessionmaker[AsyncSession],
        QueryOpenSearchClient,
        QueryNeo4jClient,
    ],
) -> None:
    client, session_factory, _opensearch, _neo4j = query_api_env
    answer_generator = QueryAnswerGenerator()
    app.dependency_overrides[dependencies.get_answer_generator] = lambda: answer_generator
    async with session_factory() as session:
        tenant, index_version_id = await _tenant_with_active_index(session)
        tenant_id = tenant.id

    created = await client.post(
        "/v1/query-runs",
        headers=_headers(tenant_id),
        json={
            "query": "Where is Acme Corporation headquartered?",
            "retrieval_index_version_id": str(index_version_id),
        },
    )
    assert created.status_code == 201
    query_run_id = created.json()["id"]

    stream = await client.get(
        f"/v1/query-runs/{query_run_id}/events/stream",
        headers=_headers(tenant_id),
    )
    assert stream.status_code == 200

    inspected = await client.get(
        f"/v1/query-runs/{query_run_id}",
        headers=_headers(tenant_id),
    )
    assert inspected.status_code == 200
    assert inspected.json()["answer_text"] == "Provider-backed answer. [c1]"
    assert len(answer_generator.requests) == 1
    assert answer_generator.requests[0].context_pack.records[0].citation_id == "c1"


@pytest.mark.asyncio
async def test_query_run_inspection_preserves_tenant_boundary(
    query_api_env: tuple[
        httpx.AsyncClient,
        async_sessionmaker[AsyncSession],
        QueryOpenSearchClient,
        QueryNeo4jClient,
    ],
) -> None:
    client, session_factory, _opensearch, _neo4j = query_api_env
    async with session_factory() as session:
        tenant, index_version_id = await _tenant_with_active_index(session)
        other = Tenant(name="query-api-other")
        session.add(other)
        await session.commit()
        tenant_id = tenant.id
        other_id = other.id

    created = await client.post(
        "/v1/query-runs",
        headers=_headers(tenant_id),
        json={
            "query": "Where is Acme Corporation headquartered?",
            "retrieval_index_version_id": str(index_version_id),
        },
    )
    assert created.status_code == 201

    foreign = await client.get(
        f"/v1/query-runs/{created.json()['id']}",
        headers=_headers(other_id),
    )
    assert foreign.status_code == 404
