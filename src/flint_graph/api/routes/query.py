from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from flint_graph.api.dependencies import (
    AnswerGeneratorDep,
    EmbeddingModelDep,
    Neo4jClientDep,
    OpenSearchClientDep,
    SessionDep,
    SettingsDep,
    SupportCheckerDep,
    TenantIdDep,
)
from flint_graph.api.schemas import (
    QueryAnswerProvenanceResponse,
    QueryCitationProvenanceResponse,
    QueryRetrievalInspectionResponse,
    QueryRunCreateRequest,
    QueryRunEventResponse,
    QueryRunResponse,
)
from flint_graph.application.embeddings import EmbeddingBatchRequest, EmbeddingInput
from flint_graph.application.query_orchestration import (
    AnswerGenerator,
    QueryCandidate,
    SupportChecker,
)
from flint_graph.application.services.lexical_projection import build_lexical_search_body
from flint_graph.application.services.query_orchestration import (
    QueryRetrieverBundle,
    run_query_retrieval_graph,
)
from flint_graph.application.services.query_provenance import (
    get_query_answer_provenance,
    get_query_citation_provenance,
)
from flint_graph.application.services.query_retrieval_inspection import inspect_query_retrieval
from flint_graph.application.services.query_runs import (
    QueryRunCreate,
    create_query_run,
    get_query_run,
    list_query_run_events,
    list_query_runs,
    transition_query_run,
)
from flint_graph.application.services.retrieval import (
    VECTOR_SEARCH_CYPHER,
    EntityNeighborhood,
    RetrievalChunkResult,
    filter_active_chunk_results,
    load_entity_neighborhood,
    resolve_index_version,
)
from flint_graph.application.services.search_readiness import require_searchable_content
from flint_graph.domain.enums import QueryRunStatus
from flint_graph.domain.errors import BadRequestError, ConflictError
from flint_graph.infrastructure.db.models import QueryRunEvent

router = APIRouter(prefix="/v1", tags=["query"])

_TERMINAL_QUERY_EVENTS = {"query.completed", "query.failed", "query.cancelled"}
_TERMINAL_QUERY_STATUSES = {
    QueryRunStatus.COMPLETED,
    QueryRunStatus.FAILED,
    QueryRunStatus.CANCELLED,
}


@router.get("/query-runs", response_model=list[QueryRunResponse])
async def list_query_runs_endpoint(
    tenant_id: TenantIdDep,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[QueryRunResponse]:
    runs = await list_query_runs(session, tenant_id=tenant_id, limit=limit)
    return [QueryRunResponse.model_validate(run) for run in runs]


@router.post(
    "/query-runs",
    response_model=QueryRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_query_run_endpoint(
    payload: QueryRunCreateRequest,
    tenant_id: TenantIdDep,
    session: SessionDep,
    settings: SettingsDep,
) -> QueryRunResponse:
    if not settings.query_enabled:
        raise BadRequestError("Query orchestration is disabled.")
    index_version = await resolve_index_version(
        session,
        tenant_id=tenant_id,
        retrieval_index_version_id=payload.retrieval_index_version_id,
    )
    readiness = await require_searchable_content(
        session,
        tenant_id=tenant_id,
        retrieval_index_version_id=index_version.id,
    )
    if not readiness.ready:
        raise ConflictError(
            "No searchable document content is available for the active retrieval index.",
            errors=[
                {
                    "reason": readiness.reason,
                    "active_index_version_id": str(index_version.id),
                    "completed_coverage_count": readiness.completed_coverage_count,
                    "running_coverage_count": readiness.running_coverage_count,
                    "failed_coverage_count": readiness.failed_coverage_count,
                }
            ],
        )
    run = await create_query_run(
        session,
        QueryRunCreate(
            tenant_id=tenant_id,
            query_text=payload.query,
            retrieval_index_version_id=index_version.id,
            metadata={
                "filters": dict(payload.filters),
                "stream": payload.stream,
            },
        ),
    )
    return QueryRunResponse.model_validate(run)


@router.get("/query-runs/{query_run_id}", response_model=QueryRunResponse)
async def get_query_run_endpoint(
    query_run_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
) -> QueryRunResponse:
    run = await get_query_run(session, tenant_id=tenant_id, query_run_id=query_run_id)
    return QueryRunResponse.model_validate(run)


@router.get("/query-runs/{query_run_id}/retrieval", response_model=QueryRetrievalInspectionResponse)
async def inspect_query_retrieval_endpoint(
    query_run_id: UUID, tenant_id: TenantIdDep, session: SessionDep,
) -> QueryRetrievalInspectionResponse:
    inspection = await inspect_query_retrieval(
        session, tenant_id=tenant_id, query_run_id=query_run_id,
    )
    return QueryRetrievalInspectionResponse.model_validate(inspection)


@router.get("/query-runs/{query_run_id}/events", response_model=list[QueryRunEventResponse])
async def list_query_run_events_endpoint(
    query_run_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
) -> list[QueryRunEventResponse]:
    events = await list_query_run_events(session, tenant_id=tenant_id, query_run_id=query_run_id)
    return [QueryRunEventResponse.model_validate(event) for event in events]


@router.get(
    "/query-runs/{query_run_id}/provenance",
    response_model=QueryAnswerProvenanceResponse,
)
async def get_query_answer_provenance_endpoint(
    query_run_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
) -> QueryAnswerProvenanceResponse:
    provenance = await get_query_answer_provenance(
        session,
        tenant_id=tenant_id,
        query_run_id=query_run_id,
    )
    return QueryAnswerProvenanceResponse.model_validate(provenance)


@router.get(
    "/query-runs/{query_run_id}/citations/{citation_id}",
    response_model=QueryCitationProvenanceResponse,
)
async def get_query_citation_provenance_endpoint(
    query_run_id: UUID,
    citation_id: str,
    tenant_id: TenantIdDep,
    session: SessionDep,
) -> QueryCitationProvenanceResponse:
    citation = await get_query_citation_provenance(
        session,
        tenant_id=tenant_id,
        query_run_id=query_run_id,
        citation_id=citation_id,
    )
    return QueryCitationProvenanceResponse.model_validate(citation)


@router.get("/query-runs/{query_run_id}/events/stream")
async def stream_query_run_events_endpoint(
    query_run_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
    settings: SettingsDep,
    opensearch_client: OpenSearchClientDep,
    neo4j_client: Neo4jClientDep,
    embedding_model: EmbeddingModelDep,
    answer_generator: AnswerGeneratorDep,
    support_checker: SupportCheckerDep,
    poll_interval_seconds: float = Query(default=0.05, ge=0.01, le=5.0),
) -> StreamingResponse:
    run = await get_query_run(session, tenant_id=tenant_id, query_run_id=query_run_id)
    index_version = await resolve_index_version(
        session,
        tenant_id=tenant_id,
        retrieval_index_version_id=run.retrieval_index_version_id,
    )
    index_snapshot = _IndexVersionSnapshot(
        id=index_version.id,
        embedding_provider=index_version.embedding_provider,
        embedding_model=index_version.embedding_model,
        vector_dimension=index_version.vector_dimension,
        neo4j_vector_index_name=index_version.neo4j_vector_index_name,
        opensearch_index_name=index_version.opensearch_index_name,
    )
    session_factory = _session_factory_from(session)
    filters = dict(run.metadata_.get("filters") or {})
    retrievers = QueryRetrieverBundle(
        lexical=_LexicalQueryRetriever(opensearch_client, index_snapshot, filters),
        vector=_VectorQueryRetriever(neo4j_client, embedding_model, index_snapshot, filters),
        graph=_GraphQueryRetriever(filters),
    )
    initial_status = run.status
    # Authentication updates last_login_at in this dependency session. Do not
    # retain its user-row lock (or an idle connection) for the whole SSE body.
    # All authorized run/index/filter values have been materialized above.
    await session.commit()
    stream = _stream_query_events(
        session_factory=session_factory,
        tenant_id=tenant_id,
        query_run_id=query_run_id,
        initial_status=initial_status,
        retrievers=retrievers,
        graph_depth=settings.query_graph_depth,
        rerank_max_results=settings.query_max_candidate_limit,
        context_token_budget=settings.query_context_token_budget,
        context_max_records=settings.query_max_context_records,
        answer_generator=answer_generator,
        support_checker=support_checker,
        min_supported_claim_ratio=settings.query_min_supported_claim_ratio,
        min_context_relevance=settings.query_min_context_relevance,
        usage_pricing=settings.usage_pricing,
        usage_currency=settings.usage_currency,
        poll_interval_seconds=poll_interval_seconds,
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@dataclass(frozen=True, slots=True)
class _IndexVersionSnapshot:
    id: UUID
    embedding_provider: str
    embedding_model: str
    vector_dimension: int
    neo4j_vector_index_name: str
    opensearch_index_name: str


class _LexicalQueryRetriever:
    def __init__(
        self,
        opensearch_client: Any,
        index_version: _IndexVersionSnapshot,
        filters: dict[str, Any] | None = None,
    ) -> None:
        self._opensearch_client = opensearch_client
        self._index_version = index_version
        self._filters = filters or {}

    async def retrieve_lexical(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        query: str,
        retrieval_index_version_id: UUID,
        limit: int,
    ) -> list[QueryCandidate]:
        hits = await self._opensearch_client.search(
            index_name=self._index_version.opensearch_index_name,
            body=build_lexical_search_body(
                tenant_id=tenant_id,
                query=query,
                limit=limit,
                filters={**self._filters, "index_version_id": retrieval_index_version_id},
            ),
        )
        chunks = await filter_active_chunk_results(
            session,
            tenant_id=tenant_id,
            results=[
                chunk
                for hit in hits
                if _matches_query_filters(
                    chunk := _chunk_result_from_opensearch_hit(hit), self._filters
                )
            ],
        )
        return [
            _chunk_candidate(
                source="lexical",
                tenant_id=tenant_id,
                retrieval_index_version_id=retrieval_index_version_id,
                chunk=chunk,
                rank=rank,
            )
            for rank, chunk in enumerate(chunks, start=1)
        ]


class _VectorQueryRetriever:
    def __init__(
        self,
        neo4j_client: Any,
        embedding_model: Any,
        index_version: _IndexVersionSnapshot,
        filters: dict[str, Any] | None = None,
    ) -> None:
        self._neo4j_client = neo4j_client
        self._embedding_model = embedding_model
        self._index_version = index_version
        self._filters = filters or {}

    async def retrieve_vector(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        query: str,
        retrieval_index_version_id: UUID,
        limit: int,
    ) -> list[QueryCandidate]:
        embedding_result = await self._embedding_model.embed_batch(
            EmbeddingBatchRequest(
                provider=cast(Any, self._index_version.embedding_provider),
                model=self._index_version.embedding_model,
                dimensions=self._index_version.vector_dimension,
                inputs=[
                    EmbeddingInput(
                        input_id="query",
                        text=query,
                        metadata={"purpose": "query_orchestration_vector_retrieval"},
                    )
                ],
                max_batch_size=1,
                config={"index_version_id": str(retrieval_index_version_id)},
            )
        )
        rows = await self._neo4j_client.execute(
            VECTOR_SEARCH_CYPHER,
            {
                "index_name": self._index_version.neo4j_vector_index_name,
                "candidate_limit": min(max(limit * 5, limit), 500),
                "vector": embedding_result.embeddings[0].vector,
                "tenant_id": str(tenant_id),
                "retrieval_index_version_id": str(retrieval_index_version_id),
                "document_id": self._filters.get("document_id"),
                "document_version_id": self._filters.get("document_version_id"),
                "chunk_id": self._filters.get("chunk_id"),
                "limit": limit,
            },
        )
        chunks = await filter_active_chunk_results(
            session,
            tenant_id=tenant_id,
            results=[
                chunk
                for row in rows
                if _matches_query_filters(chunk := _chunk_result_from_neo4j_row(row), self._filters)
            ],
        )
        return [
            _chunk_candidate(
                source="vector",
                tenant_id=tenant_id,
                retrieval_index_version_id=retrieval_index_version_id,
                chunk=chunk,
                rank=rank,
            )
            for rank, chunk in enumerate(chunks, start=1)
        ]


class _GraphQueryRetriever:
    def __init__(self, filters: dict[str, Any] | None = None) -> None:
        self._filters = filters or {}

    async def retrieve_graph(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        query: str,
        retrieval_index_version_id: UUID,
        linked_entity_ids: list[UUID],
        depth: int,
        limit: int,
    ) -> list[QueryCandidate]:
        # Relationship summaries can combine evidence from several documents.
        # Until scoped evidence reads exist, filtered runs use chunk retrieval.
        if self._filters:
            return []
        candidates: list[QueryCandidate] = []
        for entity_id in linked_entity_ids:
            if len(candidates) >= limit:
                break
            neighborhood = await load_entity_neighborhood(
                session,
                tenant_id=tenant_id,
                entity_id=entity_id,
                depth=depth,
                limit=limit - len(candidates),
            )
            candidates.extend(
                _relationship_candidates(
                    tenant_id=tenant_id,
                    retrieval_index_version_id=retrieval_index_version_id,
                    neighborhood=neighborhood,
                    start_rank=len(candidates) + 1,
                )
            )
        return candidates[:limit]


async def _stream_query_events(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    query_run_id: UUID,
    initial_status: QueryRunStatus,
    retrievers: QueryRetrieverBundle,
    graph_depth: int,
    rerank_max_results: int,
    context_token_budget: int,
    context_max_records: int,
    answer_generator: AnswerGenerator,
    support_checker: SupportChecker,
    min_supported_claim_ratio: float,
    min_context_relevance: float,
    # Defaulted so an unpriced deployment records usage with a null cost rather
    # than requiring pricing configuration to run a query at all.
    usage_pricing: dict[str, dict[str, float]] | None = None,
    usage_currency: str = "USD",
    poll_interval_seconds: float,
) -> AsyncIterator[str]:
    if initial_status != QueryRunStatus.QUEUED:
        async for event in _replay_query_events(
            session_factory=session_factory,
            tenant_id=tenant_id,
            query_run_id=query_run_id,
        ):
            yield event
        return

    queue: asyncio.Queue[str | None] = asyncio.Queue()
    task = asyncio.create_task(
        _execute_query_run(
            session_factory=session_factory,
            tenant_id=tenant_id,
            query_run_id=query_run_id,
            retrievers=retrievers,
            graph_depth=graph_depth,
            rerank_max_results=rerank_max_results,
            context_token_budget=context_token_budget,
            context_max_records=context_max_records,
            answer_generator=answer_generator,
            support_checker=support_checker,
            min_supported_claim_ratio=min_supported_claim_ratio,
            min_context_relevance=min_context_relevance,
            usage_pricing=usage_pricing,
            usage_currency=usage_currency,
            queue=queue,
        )
    )
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
    finally:
        cancellation_marker: asyncio.Task[None] | None = None
        if not task.done():
            task.cancel()
            cancellation_marker = asyncio.create_task(
                _mark_query_cancelled_with_new_session(
                    session_factory=session_factory,
                    tenant_id=tenant_id,
                    query_run_id=query_run_id,
                    delay_seconds=1.0,
                )
            )
        with suppress(asyncio.CancelledError):
            await asyncio.shield(task)
        if cancellation_marker is not None:
            with suppress(asyncio.CancelledError):
                await asyncio.shield(cancellation_marker)


async def _execute_query_run(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    query_run_id: UUID,
    retrievers: QueryRetrieverBundle,
    graph_depth: int,
    rerank_max_results: int,
    context_token_budget: int,
    context_max_records: int,
    answer_generator: AnswerGenerator,
    support_checker: SupportChecker,
    min_supported_claim_ratio: float,
    min_context_relevance: float,
    # Defaulted so an unpriced deployment records usage with a null cost rather
    # than requiring pricing configuration to run a query at all.
    usage_pricing: dict[str, dict[str, float]] | None = None,
    usage_currency: str = "USD",
    queue: asyncio.Queue[str | None],
) -> None:
    async with session_factory() as execution_session:
        last_sequence = 0

        async def emit_new_events() -> None:
            nonlocal last_sequence
            events = await _load_events_after_session(
                execution_session,
                tenant_id=tenant_id,
                query_run_id=query_run_id,
                sequence=last_sequence,
            )
            for event in events:
                last_sequence = event.sequence
                await queue.put(_sse_event(event))

        try:
            await run_query_retrieval_graph(
                execution_session,
                tenant_id=tenant_id,
                query_run_id=query_run_id,
                retrievers=retrievers,
                graph_depth=graph_depth,
                rerank_max_results=rerank_max_results,
                context_token_budget=context_token_budget,
                context_max_records=context_max_records,
                answer_generator=answer_generator,
                support_checker=support_checker,
                min_supported_claim_ratio=min_supported_claim_ratio,
                min_context_relevance=min_context_relevance,
                usage_pricing=usage_pricing,
                usage_currency=usage_currency,
                retrieval_session_factory=session_factory,
                commit_after_node=True,
                after_node_commit=emit_new_events,
            )
            await execution_session.commit()
            await emit_new_events()
        except Exception as exc:
            await execution_session.rollback()
            await _mark_query_failed(
                execution_session,
                tenant_id=tenant_id,
                query_run_id=query_run_id,
                exc=exc,
            )
            await execution_session.commit()
            await emit_new_events()
        except asyncio.CancelledError:
            await execution_session.rollback()
            await _mark_query_cancelled(
                execution_session,
                tenant_id=tenant_id,
                query_run_id=query_run_id,
            )
            await execution_session.commit()
            await emit_new_events()
            raise
        finally:
            await queue.put(None)


async def _mark_query_failed(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
    exc: Exception,
) -> None:
    run = await get_query_run(session, tenant_id=tenant_id, query_run_id=query_run_id)
    if run.status in _TERMINAL_QUERY_STATUSES:
        return
    error = {
        "stage": "query_api_stream",
        "error_code": "query_execution_failed",
        "error_message": str(exc),
    }
    await transition_query_run(
        session,
        tenant_id=tenant_id,
        query_run_id=query_run_id,
        target_status=QueryRunStatus.FAILED,
        event_type="query.failed",
        payload={"stage": "query_api_stream", "errors": [error]},
        error_code="query_execution_failed",
        error_message="Query execution failed.",
        error_details={"errors": [error]},
    )


async def _mark_query_cancelled(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
) -> None:
    run = await get_query_run(session, tenant_id=tenant_id, query_run_id=query_run_id)
    if run.status in _TERMINAL_QUERY_STATUSES:
        return
    await transition_query_run(
        session,
        tenant_id=tenant_id,
        query_run_id=query_run_id,
        target_status=QueryRunStatus.CANCELLED,
        event_type="query.cancelled",
        payload={"stage": "query_api_stream", "reason": "stream_disconnected"},
    )


async def _mark_query_cancelled_with_new_session(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    query_run_id: UUID,
    delay_seconds: float = 0.0,
) -> None:
    if delay_seconds > 0:
        await asyncio.sleep(delay_seconds)
    async with session_factory() as session:
        await _mark_query_cancelled(
            session,
            tenant_id=tenant_id,
            query_run_id=query_run_id,
        )
        await session.commit()


async def _load_events_after(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    query_run_id: UUID,
    sequence: int,
) -> list[QueryRunEvent]:
    async with session_factory() as session:
        return list(
            await session.scalars(
                select(QueryRunEvent)
                .where(
                    QueryRunEvent.tenant_id == tenant_id,
                    QueryRunEvent.query_run_id == query_run_id,
                    QueryRunEvent.sequence > sequence,
                )
                .order_by(QueryRunEvent.sequence)
            )
        )


async def _load_events_after_session(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_run_id: UUID,
    sequence: int,
) -> list[QueryRunEvent]:
    return list(
        await session.scalars(
            select(QueryRunEvent)
            .where(
                QueryRunEvent.tenant_id == tenant_id,
                QueryRunEvent.query_run_id == query_run_id,
                QueryRunEvent.sequence > sequence,
            )
            .order_by(QueryRunEvent.sequence)
        )
    )


async def _replay_query_events(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    query_run_id: UUID,
) -> AsyncIterator[str]:
    for event in await _load_events_after(
        session_factory,
        tenant_id=tenant_id,
        query_run_id=query_run_id,
        sequence=0,
    ):
        yield _sse_event(event)


def _matches_query_filters(chunk: RetrievalChunkResult, filters: dict[str, Any]) -> bool:
    values = {
        "document_id": str(chunk.document_id),
        "document_version_id": str(chunk.document_version_id),
        "chunk_id": chunk.chunk_id,
    }
    return all(values.get(name) == str(value) for name, value in filters.items())


def _chunk_candidate(
    *,
    source: str,
    tenant_id: UUID,
    retrieval_index_version_id: UUID,
    chunk: RetrievalChunkResult,
    rank: int,
) -> QueryCandidate:
    return QueryCandidate(
        candidate_id=f"{source}:chunk:{chunk.document_version_id}:{chunk.chunk_id}",
        source=cast(Any, source),
        candidate_type="chunk",
        tenant_id=tenant_id,
        retrieval_index_version_id=retrieval_index_version_id,
        source_ids={
            "document_id": str(chunk.document_id),
            "document_version_id": str(chunk.document_version_id),
            "chunk_id": chunk.chunk_id,
        },
        text_preview=chunk.text,
        raw_score=chunk.score,
        normalized_score=_normalize_score(chunk.score),
        rank=rank,
        reasons=[f"{source} retrieval"],
        metadata={
            "document_id": str(chunk.document_id),
            "document_version_id": str(chunk.document_version_id),
            "chunk_hash": chunk.chunk_hash,
            "title": chunk.title,
            "heading_path": chunk.heading_path,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "source_uri": chunk.source_uri,
            **chunk.metadata,
        },
    )


def _relationship_candidates(
    *,
    tenant_id: UUID,
    retrieval_index_version_id: UUID,
    neighborhood: EntityNeighborhood,
    start_rank: int,
) -> list[QueryCandidate]:
    names = {entity.id: entity.canonical_name for entity in neighborhood.entities}
    candidates: list[QueryCandidate] = []
    for offset, relationship in enumerate(neighborhood.relationships):
        subject = names.get(relationship.subject_entity_id, str(relationship.subject_entity_id))
        object_ = names.get(relationship.object_entity_id, str(relationship.object_entity_id))
        candidates.append(
            QueryCandidate(
                candidate_id=f"graph:relationship:{relationship.id}",
                source="graph",
                candidate_type="relationship",
                tenant_id=tenant_id,
                retrieval_index_version_id=retrieval_index_version_id,
                source_ids={"relationship_id": str(relationship.id)},
                text_preview=f"{subject} {relationship.predicate} {object_}.",
                raw_score=float(relationship.support_count),
                normalized_score=_normalize_score(float(relationship.support_count)),
                rank=start_rank + offset,
                reasons=["bounded graph neighborhood"],
                metadata={
                    "subject_entity_id": str(relationship.subject_entity_id),
                    "object_entity_id": str(relationship.object_entity_id),
                    "predicate": relationship.predicate,
                    "support_count": relationship.support_count,
                    "root_entity_id": str(neighborhood.root_entity_id),
                    "depth": neighborhood.depth,
                },
            )
        )
    return candidates


def _chunk_result_from_opensearch_hit(hit: dict[str, Any]) -> RetrievalChunkResult:
    source = hit.get("source")
    if not isinstance(source, dict):
        source = {}
    return RetrievalChunkResult(
        score=float(hit.get("score") or 0.0),
        tenant_id=UUID(str(source["tenant_id"])),
        document_id=UUID(str(source["document_id"])),
        document_version_id=UUID(str(source["document_version_id"])),
        chunk_id=str(source["chunk_id"]),
        chunk_hash=str(source["chunk_hash"]),
        text=source.get("text"),
        title=source.get("title"),
        heading_path=list(source.get("heading_path") or []),
        page_start=source.get("page_start"),
        page_end=source.get("page_end"),
        source_uri=source.get("source_uri"),
        metadata=dict(source.get("metadata") or {}),
    )


def _chunk_result_from_neo4j_row(row: dict[str, Any]) -> RetrievalChunkResult:
    node = row.get("node")
    if not isinstance(node, dict):
        node = {}
    metadata_raw = node.get("metadata_json")
    metadata = json.loads(metadata_raw) if isinstance(metadata_raw, str) else {}
    return RetrievalChunkResult(
        score=float(row.get("score") or 0.0),
        tenant_id=UUID(str(node["tenant_id"])),
        document_id=UUID(str(node["document_id"])),
        document_version_id=UUID(str(node["document_version_id"])),
        chunk_id=str(node["chunk_id"]),
        chunk_hash=str(node["chunk_hash"]),
        text=node.get("text_preview"),
        title=None,
        heading_path=list(metadata.get("heading_path") or []),
        page_start=metadata.get("page_start"),
        page_end=metadata.get("page_end"),
        source_uri=None,
        metadata=metadata,
    )


def _normalize_score(score: float) -> float:
    if score <= 0:
        return 0.0
    return min(score / (score + 1.0), 1.0)


def _sse_event(event: QueryRunEvent) -> str:
    payload = {
        "id": str(event.id),
        "query_run_id": str(event.query_run_id),
        "tenant_id": str(event.tenant_id),
        "sequence": event.sequence,
        "event_type": event.event_type,
        "payload": event.payload,
        "created_at": event.created_at.isoformat(),
    }
    return (
        f"id: {event.sequence}\n"
        f"event: {event.event_type}\n"
        f"data: {json.dumps(payload, default=str, separators=(',', ':'))}\n\n"
    )


def _session_factory_from(session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    bind = session.bind
    if bind is None:
        raise RuntimeError("database session is not bound")
    return async_sessionmaker(
        bind=cast(AsyncEngine, bind),
        expire_on_commit=False,
        autoflush=False,
    )
