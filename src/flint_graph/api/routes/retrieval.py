from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query

from flint_graph.api.dependencies import (
    AuditActorDep,
    EmbeddingModelDep,
    IndexBackfillWorkflowStarterDep,
    Neo4jClientDep,
    OpenSearchClientDep,
    SessionDep,
    SettingsDep,
    TenantAdminDep,
    TenantIdDep,
)
from flint_graph.api.schemas import (
    CanonicalEntitySummary,
    DocumentIndexCoverageResponse,
    EntityNeighborhoodResponse,
    EntityRelationshipSummary,
    IndexBackfillCreateRequest,
    IndexBackfillJobResponse,
    RetrievalChunkResultResponse,
    RetrievalIndexVersionResponse,
    RetrievalSearchRequest,
    RetrievalSearchResponse,
    SearchReadinessResponse,
)
from flint_graph.application.services.audit import record_audit_event
from flint_graph.application.services.model_readiness import ModelReadiness, get_model_readiness
from flint_graph.application.services.retrieval import (
    create_tenant_index_backfill_job,
    get_tenant_index_backfill_job,
    lexical_search,
    list_index_coverage,
    list_index_versions,
    list_tenant_index_backfill_jobs,
    load_entity_neighborhood,
    resolve_index_version,
    vector_search,
)
from flint_graph.application.services.retrieval_bootstrap import bootstrap_retrieval_index
from flint_graph.application.services.search_readiness import get_search_readiness
from flint_graph.domain.enums import (
    AuditAction,
    DocumentIndexCoverageStatus,
    RetrievalIndexVersionStatus,
)
from flint_graph.infrastructure.answer_generator_factory import (
    answer_generator_model,
    support_checker_model,
)

router = APIRouter(prefix="/v1", tags=["retrieval"])


@router.get("/model-readiness", response_model=list[ModelReadiness])
async def get_model_readiness_endpoint(
    tenant_id: TenantIdDep,
    settings: SettingsDep,
) -> list[ModelReadiness]:
    # TenantIdDep enforces the same viewer membership boundary as system readiness.
    return await get_model_readiness(settings)


@router.get("/system-readiness")
async def get_system_readiness_endpoint(
    tenant_id: TenantIdDep,
    session: SessionDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    readiness = await get_search_readiness(session, tenant_id=tenant_id)
    return {
        "setup_capabilities": {
            "preserve_active_bootstrap": True,
            "query_usage_rollups": True,
            "query_usage_invocations": True,
            "conversation_ledger": True,
            "conversation_discovery": True,
            "prior_year_followups": True,
            "chained_conversations": False,
        },
        "auth": {
            "mode": settings.auth_mode,
            "oidc_issuer": settings.oidc_issuer,
        },
        "embedding": {
            "provider": settings.embedding_provider,
            "model": settings.embedding_model,
            "dimensions": settings.embedding_dimensions,
        },
        "query": {
            "answer_provider": settings.query_answer_provider,
            "answer_model": answer_generator_model(settings),
            "support_provider": settings.query_support_provider,
            "support_model": support_checker_model(settings),
        },
        "search_readiness": SearchReadinessResponse.model_validate(readiness).model_dump(
            mode="json"
        ),
    }


@router.post(
    "/retrieval-index/bootstrap",
    response_model=RetrievalIndexVersionResponse,
)
async def bootstrap_retrieval_index_endpoint(
    tenant_id: TenantAdminDep,
    session: SessionDep,
    settings: SettingsDep,
    actor: AuditActorDep,
    preserve_active: bool = Query(default=False),
) -> RetrievalIndexVersionResponse:
    version = await bootstrap_retrieval_index(
        session, settings=settings, tenant_id=tenant_id, preserve_active=preserve_active
    )
    await record_audit_event(
        session,
        action=AuditAction.RETRIEVAL_INDEX_BOOTSTRAPPED,
        actor=actor,
        tenant_id=tenant_id,
        resource_type="retrieval_index_version",
        resource_id=version.id,
        metadata={
            "embedding_provider": version.embedding_provider,
            "embedding_model": version.embedding_model,
            "vector_dimension": version.vector_dimension,
        },
    )
    return RetrievalIndexVersionResponse.model_validate(version)


@router.post(
    "/retrieval-index/backfill-active",
    response_model=IndexBackfillJobResponse,
)
async def backfill_active_retrieval_index_endpoint(
    tenant_id: TenantAdminDep,
    session: SessionDep,
    starter: IndexBackfillWorkflowStarterDep,
    actor: AuditActorDep,
) -> IndexBackfillJobResponse:
    index_version = await resolve_index_version(
        session,
        tenant_id=tenant_id,
        retrieval_index_version_id=None,
    )
    job = await create_tenant_index_backfill_job(
        session,
        tenant_id=tenant_id,
        retrieval_index_version_id=index_version.id,
    )
    await record_audit_event(
        session,
        action=AuditAction.INDEX_BACKFILL_STARTED,
        actor=actor,
        tenant_id=tenant_id,
        resource_type="index_backfill_job",
        resource_id=job.id,
        metadata={
            "retrieval_index_version_id": str(index_version.id),
            "scope": "active_index",
        },
    )
    await session.commit()
    await starter.start_index_backfill_workflow(job_id=job.id)
    return IndexBackfillJobResponse.model_validate(job)


@router.get("/index-versions", response_model=list[RetrievalIndexVersionResponse])
async def get_index_versions(
    tenant_id: TenantIdDep,
    session: SessionDep,
    status: RetrievalIndexVersionStatus | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[RetrievalIndexVersionResponse]:
    versions = await list_index_versions(
        session,
        tenant_id=tenant_id,
        status=status,
        limit=limit,
    )
    return [RetrievalIndexVersionResponse.model_validate(version) for version in versions]


@router.get("/index-coverage", response_model=list[DocumentIndexCoverageResponse])
async def get_index_coverage(
    tenant_id: TenantIdDep,
    session: SessionDep,
    retrieval_index_version_id: UUID | None = None,
    document_id: UUID | None = None,
    document_version_id: UUID | None = None,
    status: DocumentIndexCoverageStatus | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[DocumentIndexCoverageResponse]:
    coverage = await list_index_coverage(
        session,
        tenant_id=tenant_id,
        retrieval_index_version_id=retrieval_index_version_id,
        document_id=document_id,
        document_version_id=document_version_id,
        status=status,
        limit=limit,
    )
    return [DocumentIndexCoverageResponse.model_validate(row) for row in coverage]


@router.get("/search-readiness", response_model=SearchReadinessResponse)
async def get_tenant_search_readiness(
    tenant_id: TenantIdDep,
    session: SessionDep,
    retrieval_index_version_id: UUID | None = None,
) -> SearchReadinessResponse:
    readiness = await get_search_readiness(
        session,
        tenant_id=tenant_id,
        retrieval_index_version_id=retrieval_index_version_id,
    )
    return SearchReadinessResponse.model_validate(readiness)


@router.post("/index-backfills", response_model=IndexBackfillJobResponse)
async def create_index_backfill(
    payload: IndexBackfillCreateRequest,
    tenant_id: TenantAdminDep,
    session: SessionDep,
    starter: IndexBackfillWorkflowStarterDep,
    actor: AuditActorDep,
) -> IndexBackfillJobResponse:
    job = await create_tenant_index_backfill_job(
        session,
        tenant_id=tenant_id,
        retrieval_index_version_id=payload.retrieval_index_version_id,
        document_id=payload.document_id,
        document_version_id=payload.document_version_id,
    )
    await record_audit_event(
        session,
        action=AuditAction.INDEX_BACKFILL_STARTED,
        actor=actor,
        tenant_id=tenant_id,
        resource_type="index_backfill_job",
        resource_id=job.id,
        metadata={
            "retrieval_index_version_id": str(payload.retrieval_index_version_id)
            if payload.retrieval_index_version_id
            else None,
            "document_id": str(payload.document_id) if payload.document_id else None,
            "scope": "explicit",
        },
    )
    await session.commit()
    await starter.start_index_backfill_workflow(job_id=job.id)
    return IndexBackfillJobResponse.model_validate(job)


@router.get("/index-backfills", response_model=list[IndexBackfillJobResponse])
async def list_index_backfills(
    tenant_id: TenantAdminDep,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[IndexBackfillJobResponse]:
    jobs = await list_tenant_index_backfill_jobs(session, tenant_id=tenant_id, limit=limit)
    return [IndexBackfillJobResponse.model_validate(job) for job in jobs]


@router.get("/index-backfills/{job_id}", response_model=IndexBackfillJobResponse)
async def get_index_backfill(
    job_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
) -> IndexBackfillJobResponse:
    job = await get_tenant_index_backfill_job(session, tenant_id=tenant_id, job_id=job_id)
    return IndexBackfillJobResponse.model_validate(job)


@router.post("/search/lexical", response_model=RetrievalSearchResponse)
async def search_lexical(
    payload: RetrievalSearchRequest,
    tenant_id: TenantIdDep,
    session: SessionDep,
    opensearch_client: OpenSearchClientDep,
) -> RetrievalSearchResponse:
    result = await lexical_search(
        session,
        tenant_id=tenant_id,
        opensearch_client=opensearch_client,
        query=payload.query,
        limit=payload.limit,
        retrieval_index_version_id=payload.retrieval_index_version_id,
        filters=payload.filters,
    )
    return RetrievalSearchResponse(
        index_version_id=result.index_version.id,
        results=[
            RetrievalChunkResultResponse.model_validate(chunk) for chunk in result.results
        ],
    )


@router.post("/search/vector", response_model=RetrievalSearchResponse)
async def search_vector(
    payload: RetrievalSearchRequest,
    tenant_id: TenantIdDep,
    session: SessionDep,
    neo4j_client: Neo4jClientDep,
    embedding_model: EmbeddingModelDep,
) -> RetrievalSearchResponse:
    result = await vector_search(
        session,
        tenant_id=tenant_id,
        neo4j_client=neo4j_client,
        embedding_model=embedding_model,
        query=payload.query,
        limit=payload.limit,
        retrieval_index_version_id=payload.retrieval_index_version_id,
        filters=payload.filters,
    )
    return RetrievalSearchResponse(
        index_version_id=result.index_version.id,
        results=[
            RetrievalChunkResultResponse.model_validate(chunk) for chunk in result.results
        ],
    )


@router.get("/entities/{entity_id}/neighborhood", response_model=EntityNeighborhoodResponse)
async def get_entity_neighborhood(
    entity_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
    depth: int = Query(default=1, ge=1, le=3),
    limit: int = Query(default=25, ge=1, le=100),
) -> EntityNeighborhoodResponse:
    neighborhood = await load_entity_neighborhood(
        session,
        tenant_id=tenant_id,
        entity_id=entity_id,
        depth=depth,
        limit=limit,
    )
    return EntityNeighborhoodResponse(
        root_entity_id=neighborhood.root_entity_id,
        depth=neighborhood.depth,
        entities=[
            CanonicalEntitySummary.model_validate(entity)
            for entity in neighborhood.entities
        ],
        relationships=[
            EntityRelationshipSummary.model_validate(relationship)
            for relationship in neighborhood.relationships
        ],
    )
