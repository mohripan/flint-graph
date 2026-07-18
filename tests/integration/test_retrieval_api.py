from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import atlas_rag.api.dependencies as dependencies
from atlas_rag.application.services.retrieval_index_versions import (
    RetrievalIndexVersionSpec,
    activate_retrieval_index_version,
    create_retrieval_index_version,
)
from atlas_rag.domain.enums import (
    DocumentIndexCoverageStatus,
    DocumentVersionStatus,
    EntityStatus,
    EntityType,
    RelationshipStatus,
    RetrievalIndexScope,
    SourceType,
)
from atlas_rag.infrastructure.db.base import Base
from atlas_rag.infrastructure.db.models import (
    CanonicalEntity,
    Document,
    DocumentChunk,
    DocumentIndexCoverage,
    DocumentVersion,
    EntityRelationship,
    Tenant,
)
from atlas_rag.infrastructure.db.session import get_session
from atlas_rag.main import app


class CapturingOpenSearchClient:
    def __init__(self) -> None:
        self.searches: list[tuple[str, dict[str, Any]]] = []

    async def search(self, *, index_name: str, body: dict[str, Any]) -> list[dict[str, Any]]:
        self.searches.append((index_name, body))
        return [
            {
                "id": "hit-1",
                "score": 2.5,
                "source": {
                    "tenant_id": body["query"]["bool"]["filter"][0]["term"]["tenant_id"],
                    "document_id": "11111111-1111-4111-8111-111111111111",
                    "document_version_id": "22222222-2222-4222-8222-222222222222",
                    "chunk_id": "chunk-000001",
                    "chunk_hash": "sha256:chunk",
                    "index_version_id": "33333333-3333-4333-8333-333333333333",
                    "title": "Acme Brief",
                    "text": "Acme Corporation opened a Berlin office.",
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


class CapturingNeo4jClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append((query, parameters or {}))
        return [
            {
                "score": 0.91,
                "node": {
                    "tenant_id": str((parameters or {})["tenant_id"]),
                    "document_id": "11111111-1111-4111-8111-111111111111",
                    "document_version_id": "22222222-2222-4222-8222-222222222222",
                    "chunk_id": "chunk-000001",
                    "chunk_hash": "sha256:chunk",
                    "retrieval_index_version_id": str(
                        (parameters or {})["retrieval_index_version_id"]
                    ),
                    "text_preview": "Acme Corporation opened a Berlin office.",
                    "metadata_json": '{"source_type":"upload"}',
                },
            }
        ]

    async def close(self) -> None:
        return None


class CapturingBackfillStarter:
    def __init__(self) -> None:
        self.started: list[UUID] = []

    async def start_index_backfill_workflow(self, *, job_id: UUID) -> None:
        self.started.append(job_id)


@pytest_asyncio.fixture
async def retrieval_env() -> AsyncIterator[
    tuple[
        httpx.AsyncClient,
        async_sessionmaker[AsyncSession],
        CapturingOpenSearchClient,
        CapturingNeo4jClient,
        CapturingBackfillStarter,
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

    opensearch = CapturingOpenSearchClient()
    neo4j = CapturingNeo4jClient()
    backfill_starter = CapturingBackfillStarter()
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[dependencies.get_neo4j_client] = lambda: neo4j
    if hasattr(dependencies, "get_opensearch_client"):
        app.dependency_overrides[dependencies.get_opensearch_client] = lambda: opensearch
    if hasattr(dependencies, "get_index_backfill_workflow_starter"):
        app.dependency_overrides[
            dependencies.get_index_backfill_workflow_starter
        ] = lambda: backfill_starter
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, session_factory, opensearch, neo4j, backfill_starter
    app.dependency_overrides.clear()
    await engine.dispose()


def _headers(tenant_id: UUID) -> dict[str, str]:
    return {"X-Tenant-ID": str(tenant_id)}


def _spec(*, model: str) -> RetrievalIndexVersionSpec:
    return RetrievalIndexVersionSpec(
        embedding_provider="deterministic",
        embedding_model=model,
        vector_dimension=4,
        embedding_config_hash=f"sha256:{model}",
        chunking_schema_version="1",
        chunking_config_hash="sha256:chunking",
        lexical_schema_version="1",
        neo4j_vector_index_name=f"atlas_chunks_{model.replace('-', '_')}",
        neo4j_vector_property_name="embedding_v000001",
        opensearch_index_name=f"atlas_chunks_{model.replace('-', '_')}",
        opensearch_alias_name="atlas_chunks_active",
        metadata={"model": model},
    )


async def _tenant(session: AsyncSession, name: str) -> Tenant:
    tenant = Tenant(name=name)
    session.add(tenant)
    await session.flush()
    return tenant


async def _document_version(
    session: AsyncSession,
    tenant: Tenant,
    *,
    title: str,
) -> tuple[Document, DocumentVersion, DocumentChunk]:
    document = Document(
        tenant_id=tenant.id,
        title=title,
        source_type=SourceType.UPLOAD,
        source_uri="s3://atlas/acme.txt",
        next_version_number=2,
    )
    session.add(document)
    await session.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        status=DocumentVersionStatus.ACTIVE,
        content_hash="sha256:document",
    )
    session.add(version)
    await session.flush()
    chunk = DocumentChunk(
        tenant_id=tenant.id,
        document_id=document.id,
        document_version_id=version.id,
        chunk_id="chunk-000001",
        chunk_index=0,
        text="Acme Corporation opened a Berlin office.",
        chunk_hash="sha256:chunk",
        metadata_={"source_type": "upload"},
    )
    session.add(chunk)
    await session.flush()
    return document, version, chunk


async def _active_index_versions(
    session: AsyncSession,
    tenant: Tenant,
) -> tuple[Any, Any]:
    global_version = await create_retrieval_index_version(
        session,
        scope=RetrievalIndexScope.GLOBAL,
        spec=_spec(model="global-v1"),
    )
    tenant_version = await create_retrieval_index_version(
        session,
        scope=RetrievalIndexScope.TENANT,
        tenant_id=tenant.id,
        spec=_spec(model="tenant-v1"),
    )
    await activate_retrieval_index_version(session, version_id=global_version.id)
    await activate_retrieval_index_version(session, version_id=tenant_version.id)
    return global_version, tenant_version


async def test_index_versions_and_coverage_are_tenant_scoped(
    retrieval_env: tuple[
        httpx.AsyncClient,
        async_sessionmaker[AsyncSession],
        CapturingOpenSearchClient,
        CapturingNeo4jClient,
        CapturingBackfillStarter,
    ],
) -> None:
    client, session_factory, _opensearch, _neo4j, _starter = retrieval_env
    async with session_factory() as session:
        tenant = await _tenant(session, "retrieval-api-a")
        other = await _tenant(session, "retrieval-api-b")
        document, version, _chunk = await _document_version(session, tenant, title="Acme")
        _global_version, tenant_version = await _active_index_versions(session, tenant)
        other_index = await create_retrieval_index_version(
            session,
            scope=RetrievalIndexScope.TENANT,
            tenant_id=other.id,
            spec=_spec(model="tenant-b-v1"),
        )
        coverage = DocumentIndexCoverage(
            tenant_id=tenant.id,
            document_id=document.id,
            document_version_id=version.id,
            retrieval_index_version_id=tenant_version.id,
            status=DocumentIndexCoverageStatus.COMPLETED,
            chunk_count=1,
            embedded_count=1,
            vector_count=1,
            lexical_count=1,
        )
        foreign_coverage = DocumentIndexCoverage(
            tenant_id=other.id,
            document_id=document.id,
            document_version_id=version.id,
            retrieval_index_version_id=other_index.id,
            status=DocumentIndexCoverageStatus.FAILED,
            chunk_count=1,
        )
        session.add_all([coverage, foreign_coverage])
        await session.commit()
        tenant_id = tenant.id

    versions = await client.get("/v1/index-versions", headers=_headers(tenant_id))
    assert versions.status_code == 200
    assert {row["embedding_model"] for row in versions.json()} == {
        "global-v1",
        "tenant-v1",
    }

    coverage_response = await client.get("/v1/index-coverage", headers=_headers(tenant_id))
    assert coverage_response.status_code == 200
    rows = coverage_response.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "completed"
    assert rows[0]["chunk_count"] == 1


async def test_search_readiness_summarizes_active_index_coverage(
    retrieval_env: tuple[
        httpx.AsyncClient,
        async_sessionmaker[AsyncSession],
        CapturingOpenSearchClient,
        CapturingNeo4jClient,
        CapturingBackfillStarter,
    ],
) -> None:
    client, session_factory, _opensearch, _neo4j, _starter = retrieval_env
    async with session_factory() as session:
        tenant = await _tenant(session, "retrieval-readiness")
        document, version, _chunk = await _document_version(session, tenant, title="Acme")
        _global_version, tenant_version = await _active_index_versions(session, tenant)
        session.add(
            DocumentIndexCoverage(
                tenant_id=tenant.id,
                document_id=document.id,
                document_version_id=version.id,
                retrieval_index_version_id=tenant_version.id,
                status=DocumentIndexCoverageStatus.COMPLETED,
                chunk_count=1,
                embedded_count=1,
                vector_count=1,
                lexical_count=1,
            )
        )
        await session.commit()
        tenant_id = tenant.id

    response = await client.get("/v1/search-readiness", headers=_headers(tenant_id))

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["reason"] == "searchable"
    assert body["active_index_version"]["id"] == str(tenant_version.id)
    assert body["completed_coverage_count"] == 1
    assert body["running_coverage_count"] == 0
    assert body["failed_coverage_count"] == 0
    assert body["documents"][0]["document_id"] == str(document.id)
    assert body["documents"][0]["document_version_id"] == str(version.id)
    assert body["documents"][0]["title"] == "Acme"
    assert body["documents"][0]["status"] == "searchable"


async def test_search_readiness_reports_no_active_index(
    retrieval_env: tuple[
        httpx.AsyncClient,
        async_sessionmaker[AsyncSession],
        CapturingOpenSearchClient,
        CapturingNeo4jClient,
        CapturingBackfillStarter,
    ],
) -> None:
    client, session_factory, _opensearch, _neo4j, _starter = retrieval_env
    async with session_factory() as session:
        tenant = await _tenant(session, "retrieval-readiness-empty")
        await session.commit()
        tenant_id = tenant.id

    response = await client.get("/v1/search-readiness", headers=_headers(tenant_id))

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is False
    assert body["reason"] == "no_active_index"
    assert body["active_index_version"] is None
    assert body["completed_coverage_count"] == 0
    assert body["documents"] == []


async def test_backfill_endpoint_creates_tenant_job_and_starts_workflow(
    retrieval_env: tuple[
        httpx.AsyncClient,
        async_sessionmaker[AsyncSession],
        CapturingOpenSearchClient,
        CapturingNeo4jClient,
        CapturingBackfillStarter,
    ],
) -> None:
    client, session_factory, _opensearch, _neo4j, starter = retrieval_env
    async with session_factory() as session:
        tenant = await _tenant(session, "retrieval-backfill")
        document, version, _chunk = await _document_version(session, tenant, title="Acme")
        _global_version, tenant_version = await _active_index_versions(session, tenant)
        await session.commit()
        tenant_id = tenant.id
        document_id = document.id
        version_id = version.id
        index_version_id = tenant_version.id

    response = await client.post(
        "/v1/index-backfills",
        headers=_headers(tenant_id),
        json={
            "retrieval_index_version_id": str(index_version_id),
            "document_id": str(document_id),
            "document_version_id": str(version_id),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["tenant_id"] == str(tenant_id)
    assert starter.started == [UUID(body["id"])]

    fetched = await client.get(f"/v1/index-backfills/{body['id']}", headers=_headers(tenant_id))
    assert fetched.status_code == 200
    assert fetched.json()["document_version_id"] == str(version_id)


async def test_search_endpoints_select_tenant_index_and_apply_filters(
    retrieval_env: tuple[
        httpx.AsyncClient,
        async_sessionmaker[AsyncSession],
        CapturingOpenSearchClient,
        CapturingNeo4jClient,
        CapturingBackfillStarter,
    ],
) -> None:
    client, session_factory, opensearch, neo4j, _starter = retrieval_env
    async with session_factory() as session:
        tenant = await _tenant(session, "retrieval-search")
        _document, _version, _chunk = await _document_version(session, tenant, title="Acme")
        _global_version, tenant_version = await _active_index_versions(session, tenant)
        await session.commit()
        tenant_id = tenant.id
        index_version_id = tenant_version.id

    lexical = await client.post(
        "/v1/search/lexical",
        headers=_headers(tenant_id),
        json={
            "query": "Berlin office",
            "limit": 3,
            "filters": {"source_type": "upload"},
        },
    )
    assert lexical.status_code == 200
    assert lexical.json()["index_version_id"] == str(index_version_id)
    assert lexical.json()["results"][0]["score"] == 2.5
    assert opensearch.searches[0][0] == "atlas_chunks_tenant_v1"
    filters = opensearch.searches[0][1]["query"]["bool"]["filter"]
    assert {"term": {"tenant_id": str(tenant_id)}} in filters
    assert {"term": {"index_version_id": str(index_version_id)}} in filters
    assert {"term": {"metadata.source_type": "upload"}} in filters

    vector = await client.post(
        "/v1/search/vector",
        headers=_headers(tenant_id),
        json={"query": "Berlin office", "limit": 3},
    )
    assert vector.status_code == 200
    assert vector.json()["index_version_id"] == str(index_version_id)
    assert vector.json()["results"][0]["score"] == 0.91
    assert neo4j.calls
    assert neo4j.calls[0][1]["tenant_id"] == str(tenant_id)
    assert neo4j.calls[0][1]["retrieval_index_version_id"] == str(index_version_id)


async def test_search_rejects_non_scalar_metadata_filters(
    retrieval_env: tuple[
        httpx.AsyncClient,
        async_sessionmaker[AsyncSession],
        CapturingOpenSearchClient,
        CapturingNeo4jClient,
        CapturingBackfillStarter,
    ],
) -> None:
    client, session_factory, _opensearch, _neo4j, _starter = retrieval_env
    async with session_factory() as session:
        tenant = await _tenant(session, "retrieval-search-validation")
        _document, _version, _chunk = await _document_version(session, tenant, title="Acme")
        await _active_index_versions(session, tenant)
        await session.commit()
        tenant_id = tenant.id

    response = await client.post(
        "/v1/search/lexical",
        headers=_headers(tenant_id),
        json={
            "query": "Berlin office",
            "limit": 3,
            "filters": {"tags": ["finance", "office"]},
        },
    )

    assert response.status_code == 422


async def test_entity_neighborhood_is_tenant_scoped_and_bounded(
    retrieval_env: tuple[
        httpx.AsyncClient,
        async_sessionmaker[AsyncSession],
        CapturingOpenSearchClient,
        CapturingNeo4jClient,
        CapturingBackfillStarter,
    ],
) -> None:
    client, session_factory, _opensearch, _neo4j, _starter = retrieval_env
    async with session_factory() as session:
        tenant = await _tenant(session, "retrieval-neighborhood")
        other = await _tenant(session, "retrieval-neighborhood-other")
        acme = CanonicalEntity(
            tenant_id=tenant.id,
            entity_type=EntityType.ORGANIZATION,
            canonical_name="Acme",
            normalized_name="acme",
            status=EntityStatus.ACTIVE,
            support_count=3,
        )
        berlin = CanonicalEntity(
            tenant_id=tenant.id,
            entity_type=EntityType.PLACE,
            canonical_name="Berlin",
            normalized_name="berlin",
            status=EntityStatus.ACTIVE,
            support_count=2,
        )
        europe = CanonicalEntity(
            tenant_id=tenant.id,
            entity_type=EntityType.PLACE,
            canonical_name="Europe",
            normalized_name="europe",
            status=EntityStatus.ACTIVE,
            support_count=1,
        )
        session.add_all([acme, berlin, europe])
        await session.flush()
        session.add_all(
            [
                EntityRelationship(
                    tenant_id=tenant.id,
                    subject_entity_id=acme.id,
                    predicate="located_in",
                    object_entity_id=berlin.id,
                    support_count=2,
                    status=RelationshipStatus.ACTIVE,
                ),
                EntityRelationship(
                    tenant_id=tenant.id,
                    subject_entity_id=berlin.id,
                    predicate="part_of",
                    object_entity_id=europe.id,
                    support_count=1,
                    status=RelationshipStatus.ACTIVE,
                ),
            ]
        )
        await session.commit()
        tenant_id = tenant.id
        other_id = other.id
        acme_id = acme.id

    response = await client.get(
        f"/v1/entities/{acme_id}/neighborhood?depth=1&limit=10",
        headers=_headers(tenant_id),
    )
    assert response.status_code == 200
    body = response.json()
    assert {entity["canonical_name"] for entity in body["entities"]} == {"Acme", "Berlin"}
    assert [relationship["predicate"] for relationship in body["relationships"]] == [
        "located_in"
    ]

    foreign = await client.get(
        f"/v1/entities/{acme_id}/neighborhood",
        headers=_headers(other_id),
    )
    assert foreign.status_code == 404
