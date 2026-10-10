from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import flint_graph.api.dependencies as dependencies
from flint_graph.api.routes import query as query_routes
from flint_graph.application.query_orchestration import (
    AnswerCitation,
    AnswerGenerationRequest,
    GeneratedAnswer,
)
from flint_graph.application.services.query_orchestration import QueryRetrieverBundle
from flint_graph.application.services.query_runs import get_query_run, list_query_run_events
from flint_graph.application.services.retrieval_index_versions import (
    RetrievalIndexVersionSpec,
    activate_retrieval_index_version,
    create_retrieval_index_version,
)
from flint_graph.config import Settings, get_settings
from flint_graph.domain.enums import (
    DocumentIndexCoverageStatus,
    DocumentVersionStatus,
    QueryRunStatus,
    RetrievalIndexScope,
    SourceType,
)
from flint_graph.infrastructure.db.base import Base
from flint_graph.infrastructure.db.models import (
    Document,
    DocumentChunk,
    DocumentIndexCoverage,
    DocumentVersion,
    Tenant,
)
from flint_graph.infrastructure.db.session import get_session
from flint_graph.main import app


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
                    "source_uri": "s3://flint-graph/acme.txt",
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
            text="Acme Corporation is headquartered in Berlin. [c1]",
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


@pytest_asyncio.fixture(
    params=["sqlite", "postgres"] if os.getenv("FLINT_GRAPH_PG_INTEGRATION") else ["sqlite"]
)
async def query_api_env(
    request: pytest.FixtureRequest,
) -> AsyncIterator[
    tuple[
        httpx.AsyncClient,
        async_sessionmaker[AsyncSession],
        QueryOpenSearchClient,
        QueryNeo4jClient,
    ]
]:
    schema = None
    if request.param == "postgres":
        schema = f"flint_query_test_{uuid4().hex}"
        engine = create_async_engine(
            os.getenv(
                "FLINT_GRAPH_PG_TEST_URL",
                "postgresql+asyncpg://flint_graph:flint_graph@localhost:55432/flint_graph",
            )
        )
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = engine.execution_options(schema_translate_map={None: schema})
    else:
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
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, session_factory, opensearch, neo4j
    finally:
        app.dependency_overrides.clear()
        if schema is not None:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()


def _headers(tenant_id: UUID) -> dict[str, str]:
    return {"X-Tenant-ID": str(tenant_id)}


def _expected_acme_source_ids() -> dict[str, str]:
    return {
        "document_id": "11111111-1111-4111-8111-111111111111",
        "document_version_id": "22222222-2222-4222-8222-222222222222",
        "chunk_id": "chunk-acme",
    }


def _index_spec() -> RetrievalIndexVersionSpec:
    return RetrievalIndexVersionSpec(
        embedding_provider="deterministic",
        embedding_model="query-api-v1",
        vector_dimension=4,
        embedding_config_hash="sha256:query-api-v1",
        chunking_schema_version="1",
        chunking_config_hash="sha256:chunking",
        lexical_schema_version="1",
        neo4j_vector_index_name="flint_graph_chunks_query_api_v1",
        neo4j_vector_property_name="embedding",
        opensearch_index_name="flint_graph_chunks_query_api_v1",
        opensearch_alias_name="flint_graph_chunks_active",
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


async def _add_active_document_version(
    session: AsyncSession,
    *,
    tenant: Tenant,
) -> tuple[Document, DocumentVersion]:
    document = Document(
        id=UUID("11111111-1111-4111-8111-111111111111"),
        tenant_id=tenant.id,
        title="Acme Brief",
        source_type=SourceType.UPLOAD,
        source_uri="s3://flint-graph/acme.txt",
        next_version_number=2,
    )
    session.add(document)
    await session.flush()
    version = DocumentVersion(
        id=UUID("22222222-2222-4222-8222-222222222222"),
        document_id=document.id,
        version_number=1,
        status=DocumentVersionStatus.ACTIVE,
        content_hash="sha256:document",
    )
    session.add(version)
    await session.flush()
    session.add(DocumentChunk(
        tenant_id=tenant.id, document_id=document.id, document_version_id=version.id,
        chunk_id="chunk-acme", chunk_index=0,
        text="Acme Corporation is headquartered in Berlin.", chunk_hash="sha256:chunk-acme",
        heading_path=["Overview"], page_start=1, page_end=1,
    ))
    await session.flush()
    return document, version


async def _tenant_with_searchable_content(session: AsyncSession) -> tuple[Tenant, UUID]:
    tenant, index_version_id = await _tenant_with_active_index(session)
    document, version = await _add_active_document_version(session, tenant=tenant)
    session.add(
        DocumentIndexCoverage(
            tenant_id=tenant.id,
            document_id=document.id,
            document_version_id=version.id,
            retrieval_index_version_id=index_version_id,
            status=DocumentIndexCoverageStatus.COMPLETED,
            chunk_count=1,
            embedded_count=1,
            vector_count=1,
            lexical_count=1,
        )
    )
    await session.commit()
    return tenant, index_version_id


def _sse_event_types(body: str) -> list[str]:
    return [
        line.removeprefix("event: ") for line in body.splitlines() if line.startswith("event: ")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "answer_model", "support_model"),
    [
        ("anthropic", "hosted-answer", "hosted-support"),
        ("ollama", "local-answer", "local-support"),
        ("deterministic", "deterministic", "deterministic"),
    ],
)
async def test_system_readiness_reports_effective_provider_models(
    query_api_env: tuple[
        httpx.AsyncClient, async_sessionmaker[AsyncSession], QueryOpenSearchClient, QueryNeo4jClient
    ],
    provider: str,
    answer_model: str,
    support_model: str,
) -> None:
    client, session_factory, _, _ = query_api_env
    async with session_factory() as session:
        tenant, _ = await _tenant_with_searchable_content(session)
    settings = Settings(
        env="test",
        query_answer_provider=provider,
        query_support_provider=provider,
        query_answer_model="local-answer",
        query_support_model="local-support",
        anthropic_answer_model="hosted-answer",
        anthropic_support_model="hosted-support",
        anthropic_api_key="fake-test-key",
    )
    app.dependency_overrides[get_settings] = lambda: settings
    response = await client.get("/v1/system-readiness", headers=_headers(tenant.id))
    assert response.status_code == 200
    assert response.json()["query"]["answer_model"] == answer_model
    assert response.json()["query"]["support_model"] == support_model
    assert "fake-test-key" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "error_code"),
    [("answer", "answer_generation_failed"), ("support", "support_check_failed")],
)
async def test_provider_failures_are_terminal_and_do_not_expose_provider_payloads(
    query_api_env: tuple[
        httpx.AsyncClient, async_sessionmaker[AsyncSession], QueryOpenSearchClient, QueryNeo4jClient
    ],
    operation: str,
    error_code: str,
) -> None:
    class FailingProvider:
        async def generate(self, request: Any) -> Any:
            raise RuntimeError("secret-provider-payload")

        async def check(self, request: Any) -> Any:
            raise RuntimeError("secret-provider-payload")

    client, session_factory, _, _ = query_api_env
    async with session_factory() as session:
        tenant, index_id = await _tenant_with_searchable_content(session)
    dependency = (
        dependencies.get_answer_generator
        if operation == "answer"
        else dependencies.get_support_checker
    )
    app.dependency_overrides[dependency] = lambda: FailingProvider()
    created = await client.post(
        "/v1/query-runs",
        headers=_headers(tenant.id),
        json={"query": "Where is Acme headquartered?", "retrieval_index_version_id": str(index_id)},
    )
    assert created.status_code == 201
    run_id = created.json()["id"]
    stream = await client.get(f"/v1/query-runs/{run_id}/events/stream", headers=_headers(tenant.id))
    inspected = await client.get(f"/v1/query-runs/{run_id}", headers=_headers(tenant.id))
    assert inspected.json()["status"] == "failed"
    assert inspected.json()["error_code"] == error_code
    assert _sse_event_types(stream.text)[-1] == "query.failed"
    assert "secret-provider-payload" not in stream.text
    assert "secret-provider-payload" not in inspected.text


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("FLINT_GRAPH_OLLAMA_INTEGRATION"),
    reason="Set FLINT_GRAPH_OLLAMA_INTEGRATION=1 and FLINT_GRAPH_OLLAMA_TEST_MODEL for live smoke.",
)
async def test_live_ollama_query_returns_supported_cited_answer(
    query_api_env: tuple[
        httpx.AsyncClient, async_sessionmaker[AsyncSession], QueryOpenSearchClient, QueryNeo4jClient
    ],
) -> None:
    client, session_factory, _, _ = query_api_env
    async with session_factory() as session:
        tenant, index_id = await _tenant_with_searchable_content(session)
    model = os.getenv("FLINT_GRAPH_OLLAMA_TEST_MODEL", "llama3.2")
    settings = Settings(
        env="test",
        query_answer_provider="ollama",
        query_support_provider="ollama",
        query_answer_model=model,
        query_support_model=model,
        ollama_base_url=os.getenv("FLINT_GRAPH_OLLAMA_TEST_URL", "http://localhost:11434"),
        query_answer_timeout_seconds=120,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    created = await client.post(
        "/v1/query-runs",
        headers=_headers(tenant.id),
        json={
            "query": "Where is Acme Corporation headquartered?",
            "retrieval_index_version_id": str(index_id),
        },
    )
    assert created.status_code == 201
    run_id = created.json()["id"]
    stream = await client.get(f"/v1/query-runs/{run_id}/events/stream", headers=_headers(tenant.id))
    response = await client.get(f"/v1/query-runs/{run_id}/provenance", headers=_headers(tenant.id))
    assert response.status_code == 200
    answer = response.json()
    provisional = [
        json.loads(line.removeprefix("data: "))
        for line in stream.text.splitlines()
        if line.startswith("data: ")
    ]
    assert answer["abstained"] is False, json.dumps(
        {
            "answer": answer,
            "draft": [
                event["payload"] for event in provisional if event["event_type"] == "answer.delta"
            ],
        }
    )
    assert "Berlin" in answer["answer_text"]
    assert answer["answer_citations"]
    assert all(claim["support_status"] == "supported" for claim in answer["claims"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filter_name", "filter_value"),
    [
        ("document_id", "33333333-3333-4333-8333-333333333333"),
        ("document_version_id", "44444444-4444-4444-8444-444444444444"),
        ("chunk_id", "other-chunk"),
    ],
)
async def test_filtered_query_cannot_answer_from_another_document(
    query_api_env: tuple[
        httpx.AsyncClient, async_sessionmaker[AsyncSession], QueryOpenSearchClient, QueryNeo4jClient
    ],
    filter_name: str,
    filter_value: str,
) -> None:
    client, session_factory, opensearch, neo4j = query_api_env
    async with session_factory() as session:
        tenant, index_version_id = await _tenant_with_searchable_content(session)
    created = await client.post(
        "/v1/query-runs",
        headers=_headers(tenant.id),
        json={
            "query": "Where is Acme headquartered?",
            "retrieval_index_version_id": str(index_version_id),
            "filters": {filter_name: filter_value},
        },
    )
    assert created.status_code == 201
    run_id = created.json()["id"]
    streamed = await client.get(
        f"/v1/query-runs/{run_id}/events/stream", headers=_headers(tenant.id)
    )
    assert streamed.status_code == 200
    inspected = await client.get(f"/v1/query-runs/{run_id}", headers=_headers(tenant.id))
    assert inspected.json()["query_diagnostics"]["abstention_reason"] is not None
    assert inspected.json()["answer_citations"] == []
    assert "Berlin" not in inspected.json()["answer_text"]
    assert {"term": {filter_name: filter_value}} in opensearch.searches[0][1]["query"]["bool"][
        "filter"
    ]
    assert neo4j.calls[0][1][filter_name] == filter_value


@pytest.mark.asyncio
async def test_query_rejects_filters_it_cannot_apply(
    query_api_env: tuple[
        httpx.AsyncClient, async_sessionmaker[AsyncSession], QueryOpenSearchClient, QueryNeo4jClient
    ],
) -> None:
    client, session_factory, _, _ = query_api_env
    async with session_factory() as session:
        tenant, index_version_id = await _tenant_with_searchable_content(session)
    response = await client.post(
        "/v1/query-runs",
        headers=_headers(tenant.id),
        json={
            "query": "Where is Acme?",
            "retrieval_index_version_id": str(index_version_id),
            "filters": {"unsupported": "value"},
        },
    )
    assert response.status_code == 422


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
        tenant, index_version_id = await _tenant_with_searchable_content(session)
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
        "support.checked",
        "answer.finalized",
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
            "source_ids": _expected_acme_source_ids(),
        }
    ]
    assert inspected_body["candidate_count"] == 2
    assert inspected_body["context_token_count"] == 6
    diagnostics = inspected_body["query_diagnostics"]
    assert diagnostics["retriever_candidate_counts"] == {"lexical": 1, "vector": 1}
    assert diagnostics["failed_retrievers"] == []
    assert diagnostics["retrieved_candidate_count"] == 2
    assert diagnostics["fused_candidate_count"] == 1
    assert diagnostics["reranked_candidate_count"] == 1
    assert diagnostics["context_record_count"] == 1
    assert diagnostics["context_token_count"] == 6
    assert diagnostics["skipped_context_count"] == 0
    assert diagnostics["support_status_counts"] == {"supported": 1}
    assert diagnostics["abstention_reason"] is None
    assert diagnostics["answer_provider"] == "deterministic"
    assert diagnostics["support_provider"] == "deterministic-lexical"

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
        tenant, index_version_id = await _tenant_with_searchable_content(session)
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
    assert inspected.json()["answer_text"] == "Acme Corporation is headquartered in Berlin. [c1]"
    assert len(answer_generator.requests) == 1
    assert answer_generator.requests[0].context_pack.records[0].citation_id == "c1"


@pytest.mark.asyncio
async def test_query_stream_cancellation_marks_run_cancelled(
    query_api_env: tuple[
        httpx.AsyncClient,
        async_sessionmaker[AsyncSession],
        QueryOpenSearchClient,
        QueryNeo4jClient,
    ],
) -> None:
    _client, session_factory, _opensearch, _neo4j = query_api_env
    async with session_factory() as session:
        tenant, index_version_id = await _tenant_with_searchable_content(session)
        created = await query_routes.create_query_run(
            session,
            query_routes.QueryRunCreate(
                tenant_id=tenant.id,
                query_text="Where is Acme Corporation headquartered?",
                retrieval_index_version_id=index_version_id,
            ),
        )
        await session.commit()
        tenant_id = tenant.id
        query_run_id = created.id

    queue: asyncio.Queue[str | None] = asyncio.Queue()
    task = asyncio.create_task(
        query_routes._execute_query_run(
            session_factory=session_factory,
            tenant_id=tenant_id,
            query_run_id=query_run_id,
            retrievers=QueryRetrieverBundle(),
            graph_depth=1,
            rerank_max_results=20,
            context_token_budget=4000,
            context_max_records=25,
            answer_generator=None,
            support_checker=None,
            min_supported_claim_ratio=0.5,
            min_context_relevance=0.0,
            queue=queue,
        )
    )
    first_event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert first_event is not None
    assert "event: query.started" in first_event

    task.cancel()
    with suppress(asyncio.CancelledError):
        await task

    async with session_factory() as session:
        inspected = await get_query_run(session, tenant_id=tenant_id, query_run_id=query_run_id)
        events = await list_query_run_events(
            session,
            tenant_id=tenant_id,
            query_run_id=query_run_id,
        )

    assert inspected.status == QueryRunStatus.CANCELLED
    assert events[-1].event_type == "query.cancelled"
    assert events[-1].payload == {
        "stage": "query_api_stream",
        "reason": "stream_disconnected",
    }


@pytest.mark.asyncio
async def test_query_run_api_returns_answer_provenance(
    query_api_env: tuple[
        httpx.AsyncClient,
        async_sessionmaker[AsyncSession],
        QueryOpenSearchClient,
        QueryNeo4jClient,
    ],
) -> None:
    client, session_factory, _opensearch, _neo4j = query_api_env
    async with session_factory() as session:
        tenant, index_version_id = await _tenant_with_searchable_content(session)
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

    provenance = await client.get(
        f"/v1/query-runs/{query_run_id}/provenance",
        headers=_headers(tenant_id),
    )

    assert provenance.status_code == 200
    body = provenance.json()
    assert body["query_run_id"] == query_run_id
    assert body["tenant_id"] == str(tenant_id)
    assert body["answer_text"] == "Acme Corporation is headquartered in Berlin. [c1]"
    assert body["abstained"] is False
    assert body["supported_claim_count"] == 1
    assert body["unsupported_claim_count"] == 0
    assert len(body["claims"]) == 1
    claim = body["claims"][0]
    assert claim["claim_index"] == 0
    assert claim["text"] == "Acme Corporation is headquartered in Berlin."
    assert claim["citation_ids"] == ["c1"]
    assert claim["support_status"] == "supported"
    assert claim["method"] == "deterministic-lexical"
    assert [citation["citation_id"] for citation in claim["citations"]] == ["c1"]
    citation = claim["citations"][0]
    assert citation["context_id"] == "ctx-0001"
    assert citation["candidate_id"] == (
        "lexical:chunk:22222222-2222-4222-8222-222222222222:chunk-acme"
    )
    assert citation["text"] == "Acme Corporation is headquartered in Berlin."
    assert citation["source_ids"] == _expected_acme_source_ids()
    assert body["citations"] == [citation]


@pytest.mark.asyncio
async def test_query_run_provenance_marks_deleted_citation_source_inactive(
    query_api_env: tuple[
        httpx.AsyncClient,
        async_sessionmaker[AsyncSession],
        QueryOpenSearchClient,
        QueryNeo4jClient,
    ],
) -> None:
    client, session_factory, _opensearch, _neo4j = query_api_env
    async with session_factory() as session:
        tenant, index_version_id = await _tenant_with_searchable_content(session)
        tenant_id = tenant.id

    created = await client.post(
        "/v1/query-runs",
        headers=_headers(tenant_id),
        json={
            "query": "Where is Acme Corporation headquartered?",
            "retrieval_index_version_id": str(index_version_id),
        },
    )
    query_run_id = created.json()["id"]
    await client.get(
        f"/v1/query-runs/{query_run_id}/events/stream",
        headers=_headers(tenant_id),
    )

    async with session_factory() as session:
        version = await session.get(
            DocumentVersion,
            UUID("22222222-2222-4222-8222-222222222222"),
        )
        assert version is not None
        version.status = DocumentVersionStatus.DELETED
        await session.commit()

    provenance = await client.get(
        f"/v1/query-runs/{query_run_id}/provenance",
        headers=_headers(tenant_id),
    )

    assert provenance.status_code == 200
    citation = provenance.json()["citations"][0]
    assert citation["source_document_id"] == "11111111-1111-4111-8111-111111111111"
    assert citation["source_document_version_id"] == "22222222-2222-4222-8222-222222222222"
    assert citation["source_document_version_status"] == "deleted"
    assert citation["source_active"] is False


@pytest.mark.asyncio
async def test_query_run_api_resolves_single_citation_provenance(
    query_api_env: tuple[
        httpx.AsyncClient,
        async_sessionmaker[AsyncSession],
        QueryOpenSearchClient,
        QueryNeo4jClient,
    ],
) -> None:
    client, session_factory, _opensearch, _neo4j = query_api_env
    async with session_factory() as session:
        tenant, index_version_id = await _tenant_with_searchable_content(session)
        tenant_id = tenant.id

    created = await client.post(
        "/v1/query-runs",
        headers=_headers(tenant_id),
        json={
            "query": "Where is Acme Corporation headquartered?",
            "retrieval_index_version_id": str(index_version_id),
        },
    )
    query_run_id = created.json()["id"]
    await client.get(
        f"/v1/query-runs/{query_run_id}/events/stream",
        headers=_headers(tenant_id),
    )

    resolved = await client.get(
        f"/v1/query-runs/{query_run_id}/citations/c1",
        headers=_headers(tenant_id),
    )
    missing = await client.get(
        f"/v1/query-runs/{query_run_id}/citations/c9",
        headers=_headers(tenant_id),
    )

    assert resolved.status_code == 200
    body = resolved.json()
    assert body["query_run_id"] == query_run_id
    assert body["citation_id"] == "c1"
    assert body["context_id"] == "ctx-0001"
    assert body["claims"][0]["claim_index"] == 0
    assert body["claims"][0]["text"] == "Acme Corporation is headquartered in Berlin."
    assert body["claims"][0]["support_status"] == "supported"
    assert body["claims"][0]["support_score"] == 1.0
    assert "supported" in body["claims"][0]["support_reason"]
    assert body["claims"][0]["method"] == "deterministic-lexical"
    assert missing.status_code == 404


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
        tenant, index_version_id = await _tenant_with_searchable_content(session)
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
    foreign_provenance = await client.get(
        f"/v1/query-runs/{created.json()['id']}/provenance",
        headers=_headers(other_id),
    )
    foreign_citation = await client.get(
        f"/v1/query-runs/{created.json()['id']}/citations/c1",
        headers=_headers(other_id),
    )
    assert foreign.status_code == 404
    assert foreign_provenance.status_code == 404
    assert foreign_citation.status_code == 404


@pytest.mark.asyncio
async def test_query_retrieval_trace_is_persisted_and_tenant_scoped(query_api_env: Any) -> None:
    client, session_factory, _opensearch, _neo4j = query_api_env
    async with session_factory() as session:
        tenant, index_id = await _tenant_with_searchable_content(session)
        other = Tenant(name="foreign-inspector")
        session.add(other)
        await session.commit()
    created = await client.post(
        "/v1/query-runs", headers=_headers(tenant.id),
        json={"query": "Where is Acme headquartered?", "retrieval_index_version_id": str(index_id)},
    )
    run_id = created.json()["id"]
    path = f"/v1/query-runs/{run_id}/retrieval"
    queued = await client.get(path, headers=_headers(tenant.id))
    assert queued.status_code == 200
    assert queued.json()["candidates"] == []
    await client.get(f"/v1/query-runs/{run_id}/events/stream", headers=_headers(tenant.id))
    inspected = await client.get(path, headers=_headers(tenant.id))
    repeated = await client.get(path, headers=_headers(tenant.id))
    assert inspected.json() == repeated.json()
    rows = inspected.json()["candidates"]
    assert len(rows) == 2  # Includes uncited retriever duplicates, not just answer citations.
    assert {row["source"] for row in rows} == {"lexical", "vector"}
    assert all(row["source_ids"] == _expected_acme_source_ids() for row in rows)
    assert sorted(row["rerank_rank"] for row in rows if row["rerank_rank"] is not None) == [1]
    assert all(row["document_id"] == "11111111-1111-4111-8111-111111111111" for row in rows)
    assert "Berlin" not in inspected.text  # Inspection does not duplicate source text/prompts.
    assert (await client.get(path, headers=_headers(other.id))).status_code == 404


@pytest.mark.asyncio
async def test_fresh_evaluation_capture_runs_public_query_pipeline(query_api_env: Any) -> None:
    from flint_graph.evaluation.capture import CaptureManifest, capture_dataset
    from flint_graph.evaluation.datasets import DatasetMetadata, GoldenDataset, GoldenQuery

    client, session_factory, _opensearch, _neo4j = query_api_env
    async with session_factory() as session:
        tenant, _index_id = await _tenant_with_searchable_content(session)
    dataset = GoldenDataset(
        metadata=DatasetMetadata(name="mini", version=1, tenant="query-api"),
        queries=[GoldenQuery(
            id="q1", query="Where is Acme headquartered?", query_type="factoid",
            expected_answer="Berlin", relevant_chunk_ids=["acme"], must_cite_sources=["acme"],
        )],
    )
    manifest = CaptureManifest(
        tenant_id=tenant.id, dataset_name="mini", dataset_version=1,
        document_labels={"11111111-1111-4111-8111-111111111111": "acme"},
    )
    captured = await capture_dataset(client, dataset, manifest, git_sha="test")
    evaluation = captured[0].evaluation
    assert evaluation.retrieved_chunk_ids == ["acme"]
    assert evaluation.cited_source_ids == ["acme"]
    assert "Berlin" in evaluation.answer_text
    assert evaluation.supported_claim_count == 1
    assert not evaluation.abstained


@pytest.mark.asyncio
async def test_query_inspection_does_not_wait_for_stream_authentication_lock(
    query_api_env: Any,
) -> None:
    client, session_factory, _opensearch, _neo4j = query_api_env
    async with session_factory() as session:
        if session.get_bind().dialect.name != "postgresql":
            pytest.skip("Requires PostgreSQL row locks; enable FLINT_GRAPH_PG_INTEGRATION.")
        tenant, _index_id = await _tenant_with_searchable_content(session)
    entered = asyncio.Event()
    released = asyncio.Event()

    class PausedAnswerGenerator(QueryAnswerGenerator):
        async def generate(self, request: AnswerGenerationRequest) -> GeneratedAnswer:
            entered.set()
            await released.wait()
            return await super().generate(request)

    app.dependency_overrides[dependencies.get_answer_generator] = lambda: PausedAnswerGenerator()
    created = await client.post(
        "/v1/query-runs", headers=_headers(tenant.id),
        json={"query": "Where is Acme headquartered?"},
    )
    path = f"/v1/query-runs/{created.json()['id']}"
    stream_task = asyncio.create_task(
        client.get(f"{path}/events/stream", headers=_headers(tenant.id)),
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=10)
        inspected = await asyncio.wait_for(client.get(path, headers=_headers(tenant.id)), timeout=2)
        assert inspected.status_code == 200
        assert inspected.json()["status"] == "running"
    finally:
        released.set()
        await stream_task


@pytest.mark.asyncio
async def test_long_search_preview_is_bounded_but_answer_context_is_complete(query_api_env: Any):
    from sqlalchemy import select

    from flint_graph.infrastructure.db.models import QueryContextPackRecord, QueryRunCandidate

    client, session_factory, _opensearch, _neo4j = query_api_env
    text = ("Background information. " * 100) + "The project codename is Quartz."
    assert 2000 < len(text) < 4000
    async with session_factory() as session:
        tenant, _index_id = await _tenant_with_searchable_content(session)
        chunk = await session.scalar(
            select(DocumentChunk).where(DocumentChunk.tenant_id == tenant.id)
        )
        chunk.text = text
        await session.commit()

    class LongSearch(QueryOpenSearchClient):
        async def search(self, *, index_name: str, body: dict[str, Any]) -> list[dict[str, Any]]:
            hits = await super().search(index_name=index_name, body=body)
            hits[0]["source"]["text"] = text
            return hits

    app.dependency_overrides[dependencies.get_opensearch_client] = lambda: LongSearch()
    created = await client.post("/v1/query-runs", headers=_headers(tenant.id),
                                json={"query": "What is the project codename?"})
    run_id = UUID(created.json()["id"])
    path = f"/v1/query-runs/{run_id}"
    await client.get(f"{path}/events/stream", headers=_headers(tenant.id))
    inspected = await client.get(path, headers=_headers(tenant.id))
    assert inspected.json()["status"] == "completed"
    async with session_factory() as session:
        records = list(await session.scalars(select(QueryContextPackRecord).where(
            QueryContextPackRecord.query_run_id == run_id
        )))
        assert records[0].text == text
        rows = list(await session.scalars(select(QueryRunCandidate).where(
            QueryRunCandidate.query_run_id == run_id
        )))
        assert all(len(row.text_preview or "") <= 2000 for row in rows)


@pytest.mark.asyncio
async def test_same_named_chunks_from_different_documents_do_not_collide(
    query_api_env: Any,
) -> None:
    client, session_factory, _opensearch, _neo4j = query_api_env
    other_document_id, other_version_id = uuid4(), uuid4()
    async with session_factory() as session:
        tenant, _index_id = await _tenant_with_searchable_content(session)
        document = Document(
            id=other_document_id, tenant_id=tenant.id, title="Globex",
            source_type=SourceType.UPLOAD, next_version_number=2,
        )
        session.add(document)
        await session.flush()
        session.add(DocumentVersion(
            id=other_version_id, document_id=document.id, version_number=1,
            status=DocumentVersionStatus.ACTIVE, content_hash="sha256:globex",
        ))
        await session.flush()
        session.add(DocumentChunk(
            tenant_id=tenant.id, document_id=document.id, document_version_id=other_version_id,
            chunk_id="chunk-acme", chunk_index=0,
            text="Globex Industries is based in Osaka.", chunk_hash="sha256:chunk-acme",
        ))
        await session.commit()

    class MultipleDocumentSearch(QueryOpenSearchClient):
        async def search(self, *, index_name: str, body: dict[str, Any]) -> list[dict[str, Any]]:
            hits = await super().search(index_name=index_name, body=body)
            hits.append({"id": "globex-hit", "score": 1.5, "source": {
                **hits[0]["source"], "document_id": str(other_document_id),
                "document_version_id": str(other_version_id), "title": "Globex",
                "text": "Globex Industries is based in Osaka.",
            }})
            return hits

    app.dependency_overrides[dependencies.get_opensearch_client] = lambda: MultipleDocumentSearch()
    created = await client.post(
        "/v1/query-runs", headers=_headers(tenant.id),
        json={"query": "Where is Acme Corporation headquartered?"},
    )
    path = f"/v1/query-runs/{created.json()['id']}"
    await client.get(f"{path}/events/stream", headers=_headers(tenant.id))
    inspected = await client.get(path, headers=_headers(tenant.id))
    assert inspected.json()["status"] == "completed"
    assert "Berlin" in inspected.json()["answer_text"]
    trace = (await client.get(f"{path}/retrieval", headers=_headers(tenant.id))).json()
    rows = trace["candidates"]
    assert len(rows) == 3
    assert len({row["candidate_id"] for row in rows}) == 3
    assert len({row["source_ids"]["document_version_id"] for row in rows}) == 2
    assert {row["source_ids"]["chunk_id"] for row in rows} == {"chunk-acme"}


@pytest.mark.asyncio
async def test_query_run_creation_rejects_active_index_without_searchable_content(
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
        await _add_active_document_version(session, tenant=tenant)
        await session.commit()
        tenant_id = tenant.id

    response = await client.post(
        "/v1/query-runs",
        headers=_headers(tenant_id),
        json={
            "query": "Where is Acme Corporation headquartered?",
            "retrieval_index_version_id": str(index_version_id),
        },
    )

    assert response.status_code == 409
    body = response.json()
    assert body["detail"] == (
        "No searchable document content is available for the active retrieval index."
    )
    assert body["errors"][0]["reason"] == "no_completed_coverage"
    assert body["errors"][0]["active_index_version_id"] == str(index_version_id)
